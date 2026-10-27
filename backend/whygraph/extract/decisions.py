"""Turn PRs, issues, commit messages and design docs into Decision nodes.

* `explicit`  – the source states the reason; a verbatim quote is verified against the source text.
* `inferred`  – the LLM had to guess (no stated rationale, or the quote could not be verified).
                These land in the admin review queue.
Revert commits become decisions deterministically (no LLM needed).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from rapidfuzz import fuzz

from .. import db, llm
from ..config import REPO_PATH, REPO_SLUG

log = logging.getLogger(__name__)

SIGNAL = re.compile(
    r"\b(because|since|instead|in order to|so that|reason|rather than|trade-?off|backwards?[- ]compat|deprecat\w*|"
    r"revert\w*|security|performance|slow|faster|breaks?|breaking|avoid|workaround|regression|decided|prefer|"
    r"intentional\w*|by design|consisten\w*|the problem|the issue|motivation|why|downside|upside|alternative)\b",
    re.I,
)
BOT = re.compile(r"(dependabot|pre-commit-ci|github-actions|renovate)", re.I)
TRIVIAL_TITLE = re.compile(r"\b(typo|bump|release \d|update (changelog|changes)|pre-commit|requirements|"
                           r"fix (a )?link|docs?\b|documentation|spelling|grammar|readme|ci\b|test(s|ing)? only)\b", re.I)

SYSTEM = """You are a software archaeologist. You read pull requests, issues, commit messages and design notes
from the open-source repository {repo} and extract DESIGN DECISIONS: deliberate choices about how the code
should behave or be structured, together with the reasons given for them.

Rules:
- Only extract real decisions (a behaviour, default value, API shape, dependency, structure, deprecation or
  removal that someone chose deliberately). Routine bug fixes with no design reasoning, typo fixes, refactors
  with no stated reason, and release chores yield NO decision.
- "rationale" must explain WHY. If the source states the reason, set "explicit": true. If you can only guess
  the reason, set "explicit": false and say so in the rationale.
- "quote" MUST be copied VERBATIM (exact characters) from the source text: the single sentence or two that best
  evidences the rationale, max 300 characters. Never paraphrase inside "quote".
- "entities": code identifiers the decision is about (function, method, class, attribute or CONFIG_KEY names),
  exactly as written in code, without parentheses.
- "alternatives": options that were considered and rejected, if mentioned.
- "supersedes": if the text says this replaces, reverts or changes an earlier approach, describe that earlier
  approach in a few words and list any referenced numbers like "#1234"; otherwise null.
- At most 3 decisions per source. Be concise. Output JSON only."""

PROMPT = """Extract decisions from each source below.

Return JSON: {{"results": [{{"source_id": "<id>", "decisions": [
  {{"title": "<= 10 words", "decision": "what was decided, 1-2 sentences",
    "rationale": "why, 1-3 sentences", "alternatives": ["..."], "quote": "verbatim from source",
    "explicit": true, "kind": "design|default|api|deprecation|removal|compat|security|performance|bugfix|revert",
    "entities": ["name"], "supersedes": {{"description": "...", "refs": ["#123"]}} }} ] }} ]}}

{sources}"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def verify_quote(quote: str, haystack: str) -> bool:
    q, h = _norm(quote), _norm(haystack)
    if not q or len(q) < 15:
        return False
    if q in h:
        return True
    return fuzz.partial_ratio(q, h) >= 92


def _score(text: str) -> int:
    return len(SIGNAL.findall(text or ""))


# --------------------------------------------------------------------------- candidates

def pr_candidates() -> list[dict]:
    rows = db.run(
        """MATCH (p:PullRequest)
           WHERE NOT EXISTS { MATCH (:Decision)-[:EXTRACTED_FROM]->(p) }
           OPTIONAL MATCH (author:Person)-[:AUTHORED]->(p)
           OPTIONAL MATCH (c:Commit)-[:PART_OF]->(p)
           OPTIONAL MATCH (c)-[m:MODIFIED]->(e:CodeEntity) WHERE e.kind <> 'module'
           WITH p, author, e, sum(m.lines) AS lines
           WITH p, author, collect(CASE WHEN e IS NULL THEN null ELSE {name: e.qualname, lines: lines} END) AS ents
           OPTIONAL MATCH (p)-[:CLOSES|REFERENCES]->(i:Issue)
           RETURN p.number AS number, p.title AS title, p.body AS body, p.discussion AS discussion,
                  p.merged_at AS date, author.login AS login, ents,
                  collect(DISTINCT {number: i.number, title: i.title, body: left(i.body, 1500)}) AS issues"""
    )
    out = []
    for r in rows:
        if BOT.search(r["login"] or "") or not r["ents"]:
            continue
        if TRIVIAL_TITLE.search(r["title"] or "") and _score(r["body"]) < 2:
            continue
        issues = [i for i in r["issues"] if i.get("number")]
        text = " ".join([r["title"] or "", r["body"] or "", r["discussion"] or ""] +
                        [f"{i['title']} {i['body']}" for i in issues])
        score = _score(text)
        touches_config = any((e["name"] or "").startswith("config:") for e in r["ents"])
        if score < 2 and len(r["body"] or "") < 300 and not touches_config and not issues:
            continue
        ents = sorted(r["ents"], key=lambda e: -(e["lines"] or 0))
        out.append({**r, "issues": issues, "ents": ents, "score": score + min(len(ents), 5)})
    out.sort(key=lambda r: -r["score"])
    return out


def commit_candidates() -> list[dict]:
    rows = db.run(
        """MATCH (c:Commit)-[m:MODIFIED]->(e:CodeEntity)
           WHERE NOT c.is_merge AND NOT c.trivial AND NOT c.formatting AND NOT c.is_revert
             AND NOT (c)-[:PART_OF]->(:PullRequest) AND size(c.message) > 160 AND e.kind <> 'module'
             AND NOT EXISTS { MATCH (:Decision)-[:EXTRACTED_FROM]->(c) }
           OPTIONAL MATCH (a:Person)-[:AUTHORED]->(c)
           WITH c, a, collect({name: e.qualname, lines: m.lines}) AS ents
           RETURN c.sha AS sha, c.message AS message, c.date AS date, a.name AS author, ents"""
    )
    out = [r for r in rows if _score(r["message"]) >= 1]
    for r in out:
        r["score"] = _score(r["message"])
    out.sort(key=lambda r: -r["score"])
    return out


def design_doc_sections() -> list[dict]:
    p = REPO_PATH / "docs" / "design.rst"
    if not p.exists():
        return []
    text = p.read_text()
    lines = text.splitlines()
    sections, cur, title = [], [], "Design Decisions in Flask"
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and re.fullmatch(r"-{3,}", lines[i + 1].strip()) and line.strip():
            if cur:
                sections.append((title, "\n".join(cur)))
            title, cur = line.strip(), []
        elif re.fullmatch(r"[-=]{3,}", line.strip()):
            continue
        else:
            cur.append(line)
    if cur:
        sections.append((title, "\n".join(cur)))
    return [{"id": f"doc:design.rst#{re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')}", "title": t, "text": body.strip()}
            for t, body in sections if len(body.strip()) > 200]


# --------------------------------------------------------------------------- source formatting

def _pr_source(r: dict) -> tuple[str, str]:
    sid = f"pr:{r['number']}"
    issues = "\n".join(f"#{i['number']} {i['title']}: {i['body'] or ''}" for i in r["issues"])[:2500]
    body = (r["body"] or "")[:3500]
    disc = (r["discussion"] or "")[:3500]
    ents = ", ".join(e["name"] for e in r["ents"][:15])
    shown = (f"SOURCE {sid}: Pull request #{r['number']} \"{r['title']}\" by {r['login']} ({(r['date'] or '')[:10]})\n"
             f"Code changed: {ents}\n--- description ---\n{body}\n--- linked issues ---\n{issues or '(none)'}\n"
             f"--- review discussion ---\n{disc or '(none)'}")
    raw = " ".join([r["title"] or "", body, issues, disc])
    return shown, raw


def _commit_source(r: dict) -> tuple[str, str]:
    sid = f"commit:{r['sha'][:12]}"
    ents = ", ".join(e["name"] for e in r["ents"][:15])
    msg = r["message"][:3000]
    return (f"SOURCE {sid}: Commit {r['sha'][:8]} by {r['author']} ({(r['date'] or '')[:10]})\n"
            f"Code changed: {ents}\n--- message ---\n{msg}"), msg


def _doc_source(r: dict) -> tuple[str, str]:
    body = r["text"][:5000]
    return f"SOURCE {r['id']}: Design document docs/design.rst, section \"{r['title']}\"\n{body}", body


# --------------------------------------------------------------------------- writing

def _write(decisions: list[dict]) -> None:
    db.run_batched(
        """UNWIND $rows AS d
           MERGE (n:Decision {id: d.id})
           SET n.title = d.title, n.decision = d.decision, n.rationale = d.rationale,
               n.alternatives = d.alternatives, n.quote = d.quote, n.quote_verified = d.quote_verified,
               n.status = d.status, n.kind = d.kind, n.date = d.date, n.epoch = d.epoch,
               n.source_type = d.source_type, n.source_ref = d.source_ref, n.source_url = d.source_url,
               n.entity_names = d.entities, n.supersedes_hint = d.supersedes_hint,
               n.created_by = 'llm', n.inferred_from = d.inferred_from, n.embedding = null""",
        decisions,
    )
    for d in decisions:
        st, ref = d["source_type"], d["source_ref"]
        if st == "pr":
            db.run("""MATCH (n:Decision {id: $id}), (p:PullRequest {number: $num})
                      MERGE (n)-[:EXTRACTED_FROM]->(p)
                      WITH n, p
                      OPTIONAL MATCH (c:Commit)-[:PART_OF]->(p) WHERE NOT c.is_merge
                      FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (n)-[:IMPLEMENTED_BY]->(c))
                      WITH DISTINCT n, p
                      OPTIONAL MATCH (p)-[:CLOSES|REFERENCES]->(i:Issue)
                      FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | MERGE (n)-[:MOTIVATED_BY]->(i))""",
                   id=d["id"], num=int(ref))
        elif st == "commit":
            db.run("""MATCH (n:Decision {id: $id}), (c:Commit) WHERE c.sha STARTS WITH $sha
                      MERGE (n)-[:EXTRACTED_FROM]->(c) MERGE (n)-[:IMPLEMENTED_BY]->(c)
                      WITH n, c OPTIONAL MATCH (c)-[:REFERENCES]->(i:Issue)
                      FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | MERGE (n)-[:MOTIVATED_BY]->(i))""",
                   id=d["id"], sha=ref)
        elif st == "doc":
            db.run("""MATCH (n:Decision {id: $id})
                      MERGE (doc:DesignDoc {id: $doc}) SET doc.path = 'docs/design.rst', doc.section = $section,
                          doc.url = $url
                      MERGE (n)-[:EXTRACTED_FROM]->(doc)""",
                   id=d["id"], doc=d["doc_id"], section=d["doc_section"], url=d["source_url"])
        link_entities(d["id"], d["entities"], restrict_to_modified=st != "doc")


def link_entities(decision_id: str, names: list[str], restrict_to_modified: bool = True) -> None:
    """AFFECTS edges. For code-backed sources: the entities the implementing commits modified (named ones flagged).
    For docs / admin decisions: entities resolved by name."""
    names = [n.strip().strip("()`") for n in (names or []) if n and n.strip()]
    short = sorted({n.split(".")[-1] for n in names})
    if restrict_to_modified:
        db.run(
            """MATCH (d:Decision {id: $id})-[:IMPLEMENTED_BY]->(c:Commit)-[m:MODIFIED]->(e:CodeEntity)
               WHERE e.kind <> 'module'
               WITH d, e, sum(m.lines) AS lines,
                    (e.name IN $short OR e.qualname IN $names OR replace(e.qualname, 'config:', '') IN $short) AS named
               ORDER BY named DESC, lines DESC
               WITH d, collect({e: e, named: named, lines: lines}) AS rows
               WITH d, [r IN rows WHERE r.named] + [r IN rows WHERE NOT r.named][..8] AS keep
               UNWIND keep AS r
               WITH d, r.e AS e, r.named AS named, r.lines AS lines
               MERGE (d)-[a:AFFECTS]->(e) SET a.mentioned = named, a.lines = lines""",
            id=decision_id, short=short, names=names,
        )
    # Name-resolved links (always, so docs and named entities outside the diff still connect).
    if short:
        db.run(
            """MATCH (d:Decision {id: $id})
               MATCH (e:CodeEntity) WHERE e.alive AND e.kind <> 'module'
                 AND (e.name IN $short OR replace(e.qualname, 'config:', '') IN $short)
               WITH d, e ORDER BY e.churn DESC
               WITH d, e.name AS nm, collect(e)[..2] AS es
               UNWIND es AS e
               MERGE (d)-[a:AFFECTS]->(e) ON CREATE SET a.mentioned = true, a.lines = 0""",
            id=decision_id, short=short,
        )


def _to_epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _materialize(sid: str, items: list[dict], meta: dict, raw: str) -> list[dict]:
    out = []
    for k, it in enumerate(items[:3]):
        if not it.get("decision") or not it.get("title"):
            continue
        quote = (it.get("quote") or "").strip()
        verified = verify_quote(quote, raw)
        explicit = bool(it.get("explicit")) and verified
        sup = it.get("supersedes") or None
        out.append({
            "id": f"{sid}#{k}",
            "title": it["title"][:120],
            "decision": it["decision"][:600],
            "rationale": (it.get("rationale") or "")[:900],
            "alternatives": [a[:200] for a in (it.get("alternatives") or []) if isinstance(a, str)][:5],
            "quote": quote[:400] if verified else (quote[:400] if quote else ""),
            "quote_verified": verified,
            "status": "explicit" if explicit else "inferred",
            "inferred_from": None if explicit else "text",
            "kind": (it.get("kind") or "design")[:20],
            "entities": [e for e in (it.get("entities") or []) if isinstance(e, str)][:10],
            "supersedes_hint": (f"{sup.get('description', '')} {' '.join(sup.get('refs') or [])}".strip()
                                if isinstance(sup, dict) else None),
            **meta,
        })
    return out


def _run_batches(sources: list[tuple[str, str, str, dict]], max_chars: int = 22000, per_call: int = 6) -> int:
    """sources: (sid, shown_text, raw_text, meta)."""
    total = 0
    batch: list = []
    size = 0

    def flush():
        nonlocal total, batch, size
        if not batch:
            return
        prompt = PROMPT.format(sources="\n\n=====\n\n".join(s[1] for s in batch))
        try:
            data = llm.generate_json(prompt, system=SYSTEM.format(repo=REPO_SLUG), namespace="extract")
        except llm.LLMUnavailable as e:
            log.error("LLM unavailable, stopping extraction: %s", e)
            batch, size = [], 0
            raise
        results = {r.get("source_id"): r.get("decisions") or [] for r in (data.get("results") or [])} \
            if isinstance(data, dict) else {}
        decisions = []
        for sid, _, raw, meta in batch:
            decisions.extend(_materialize(sid, results.get(sid, []), meta, raw))
        # mark empty sources so they are not re-sent next run
        _write(decisions)
        empty = [s[0] for s in batch if not results.get(s[0])]
        if empty:
            db.run("UNWIND $ids AS sid MERGE (x:ExtractionDone {sid: sid})", ids=empty)
        total += len(decisions)
        log.info("batch: %d sources -> %d decisions (total %d)", len(batch), len(decisions), total)
        batch, size = [], 0

    for s in sources:
        if size + len(s[1]) > max_chars or len(batch) >= per_call:
            flush()
        batch.append(s)
        size += len(s[1])
    flush()
    return total


def _done_ids() -> set[str]:
    return {r["sid"] for r in db.run("MATCH (x:ExtractionDone) RETURN x.sid AS sid")}


def extract_explicit(limit_prs: int = 400, limit_commits: int = 120, docs: bool = True) -> int:
    done = _done_ids()
    sources = []
    if docs:
        for r in design_doc_sections():
            if r["id"] in done or db.run("MATCH (d:Decision) WHERE d.id STARTS WITH $p RETURN d LIMIT 1", p=r["id"]):
                continue
            shown, raw = _doc_source(r)
            sources.append((r["id"], shown, raw, {
                "date": None, "epoch": None, "source_type": "doc", "source_ref": r["id"], "doc_id": r["id"],
                "doc_section": r["title"],
                "source_url": f"https://github.com/{REPO_SLUG}/blob/main/docs/design.rst"}))
    for r in pr_candidates()[:limit_prs]:
        sid = f"pr:{r['number']}"
        if sid in done:
            continue
        shown, raw = _pr_source(r)
        sources.append((sid, shown, raw, {
            "date": r["date"], "epoch": _to_epoch(r["date"]), "source_type": "pr", "source_ref": str(r["number"]),
            "source_url": f"https://github.com/{REPO_SLUG}/pull/{r['number']}"}))
    for r in commit_candidates()[:limit_commits]:
        sid = f"commit:{r['sha'][:12]}"
        if sid in done:
            continue
        shown, raw = _commit_source(r)
        sources.append((sid, shown, raw, {
            "date": r["date"], "epoch": _to_epoch(r["date"]), "source_type": "commit", "source_ref": r["sha"][:12],
            "source_url": f"https://github.com/{REPO_SLUG}/commit/{r['sha']}"}))
    log.info("Extracting from %d sources", len(sources))
    return _run_batches(sources)


def revert_decisions() -> int:
    """Deterministic: each revert commit is a decision that supersedes what it reverted."""
    rows = db.run(
        """MATCH (r:Commit)-[:REVERTS]->(t:Commit) WHERE EXISTS { (r)-[:MODIFIED]->(:CodeEntity) }
           OPTIONAL MATCH (r)-[:PART_OF]->(rp:PullRequest)
           RETURN r.sha AS sha, r.subject AS subject, r.message AS message, r.date AS date, r.epoch AS epoch,
                  t.sha AS target, rp.number AS pr"""
    )
    for r in rows:
        did = f"revert:{r['sha'][:12]}"
        body = r["message"].split("\n", 1)[1].strip() if "\n" in r["message"] else ""
        body = re.sub(r"This reverts commit [0-9a-f]+\.?", "", body).strip()
        db.run(
            """MERGE (d:Decision {id: $id})
               SET d.title = $title, d.decision = $decision, d.rationale = $rationale, d.quote = $quote,
                   d.quote_verified = true, d.status = $status, d.kind = 'revert', d.date = $date, d.epoch = $epoch,
                   d.source_type = 'commit', d.source_ref = $short, d.created_by = 'git',
                   d.source_url = $url, d.alternatives = []
               WITH d MATCH (r:Commit {sha: $sha}) MERGE (d)-[:EXTRACTED_FROM]->(r) MERGE (d)-[:IMPLEMENTED_BY]->(r)""",
            id=did, title=r["subject"][:120], decision=f"Reverted commit {r['target'][:8]}: {r['subject']}",
            rationale=body[:600] or "The revert commit gives no reason; check the linked PR or issue.",
            quote=(body or r["subject"])[:300], status="explicit" if body else "inferred",
            date=r["date"], epoch=r["epoch"], short=r["sha"][:12], sha=r["sha"],
            url=f"https://github.com/{REPO_SLUG}/commit/{r['sha']}",
        )
        link_entities(did, [], restrict_to_modified=True)
    log.info("Created %d revert decisions", len(rows))
    return len(rows)
