"""Answer "why is it like this?" with an evidence chain.

Pipeline (GraphRAG):
  1. resolve code entities named in the question (exact name -> full-text -> vector)
  2. retrieve decisions: graph neighbours of those entities  ∪  vector search over decisions
  3. expand each decision's evidence subgraph (sources, issues, commits, people, supersession)
  4. score confidence from graph facts; refuse when the graph has no answer
  5. let the LLM write the answer, citing only retrieved evidence
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

from .. import db, llm
from ..config import ANSWER_DEADLINE, ANSWER_MODELS, REPO_SLUG
from ..embed import embed_query
from . import confidence

log = logging.getLogger(__name__)

IDENT = re.compile(r"`([^`]+)`|\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+|[A-Z][A-Z0-9]*_[A-Z0-9_]+|"
                   r"[a-z]+_[a-z0-9_]+|[A-Z][a-z]+[A-Z][A-Za-z]+)\b")
STOP = {"why", "what", "how", "is", "the", "a", "an", "does", "do", "this", "that", "like", "it", "in", "of", "to",
        "flask", "code", "and", "or", "for", "was", "were", "are", "be", "on", "with", "way", "there"}
LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')

# Neo4j reports cosine as (1 + cos) / 2, and bge scores cluster high: unrelated text sits around 0.80-0.86.
MIN_VEC = 0.875   # below this a decision needs a graph link to the question's code to be considered
VEC_FLOOR = 0.82  # rescale vector scores from here up to the best hit of the query


COMMON_CAPS = {"why", "what", "how", "when", "where", "who", "is", "does", "do", "did", "was", "are", "can", "should",
               "flask", "python", "the", "a", "an", "i", "in", "on", "it", "this", "and", "or", "not", "instead"}


def unknown_terms(question: str) -> list[str]:
    """Proper nouns / identifiers in the question that no code entity and no recorded decision mentions.
    (Raw issues are not counted: users mention everything there.)"""
    missing = []
    for code in re.findall(r"`([^`]+)`", question):
        name = code.strip("()").split(".")[-1]
        if not db.run("MATCH (e:CodeEntity) WHERE e.name = $n OR e.qualname = $q RETURN 1 LIMIT 1",
                      n=name, q=code.strip("()")):
            missing.append(code)
    plain = re.sub(r"`[^`]+`", " ", question)
    for t in sorted(set(re.findall(r"(?<![\w.])([A-Z][A-Za-z0-9]{2,})", plain))):
        if t.lower() in COMMON_CAPS:
            continue
        q = LUCENE_SPECIAL.sub(r"\\\1", t)
        if not any(db.run(f"CALL db.index.fulltext.queryNodes('{ix}', $q) YIELD node RETURN 1 LIMIT 1", q=q)
                   for ix in ("entity_text", "decision_text")):
            missing.append(t)
    return missing


def _resolve_entities(question: str, qvec: list[float]) -> list[dict]:
    found: dict[str, dict] = {}
    idents = {(a or b).strip("()") for a, b in IDENT.findall(question)}
    idents |= {w for w in re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", question)}
    names = {i.split(".")[-1] for i in idents if i.lower() not in STOP}
    if names:
        for r in db.run(
            """MATCH (e:CodeEntity) WHERE e.alive AND e.kind <> 'module'
                 AND (e.name IN $names OR e.qualname IN $quals)
               RETURN e {.id, .qualname, .kind, .path, .name, .churn} AS e ORDER BY e.churn DESC LIMIT 6""",
            names=sorted(names), quals=sorted(idents),
        ):
            found[r["e"]["id"]] = {**r["e"], "match": "exact"}
    if not found:
        # only identifier-looking tokens: plain English words ("used", "still") match docstrings at random
        words = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", question)
                 if w.lower() not in STOP and ("_" in w or re.search(r"[a-z][A-Z]|^[A-Z]{2,}", w))]
        if words:
            q = " OR ".join(LUCENE_SPECIAL.sub(r"\\\1", w) for w in words)
            for r in db.run(
                """CALL db.index.fulltext.queryNodes('entity_text', $q) YIELD node, score
                   WHERE node.alive AND node.kind <> 'module' AND score > 2.5
                   RETURN node {.id, .qualname, .kind, .path, .name, .churn} AS e, score LIMIT 3""",
                q=q,
            ):
                found.setdefault(r["e"]["id"], {**r["e"], "match": "text"})
    if not found:
        for r in db.run(
            """CALL db.index.vector.queryNodes('entity_embedding', 3, $v) YIELD node, score
               WHERE score > 0.90
               RETURN node {.id, .qualname, .kind, .path, .name, .churn} AS e, score""",
            v=qvec,
        ):
            found.setdefault(r["e"]["id"], {**r["e"], "match": "semantic"})
    return list(found.values())


DECISION_DETAIL = """
MATCH (d:Decision) WHERE d.id IN $ids
OPTIONAL MATCH (d)-[:EXTRACTED_FROM]->(src)
OPTIONAL MATCH (d)-[:MOTIVATED_BY]->(i:Issue)
WITH d, collect(DISTINCT src) AS srcs, collect(DISTINCT i) AS issues
OPTIONAL MATCH (d)-[:IMPLEMENTED_BY]->(c:Commit)
WITH d, srcs, issues, collect(DISTINCT c) AS commits
OPTIONAL MATCH (d)-[a:AFFECTS]->(e:CodeEntity)
WITH d, srcs, issues, commits, collect(DISTINCT {id: e.id, qualname: e.qualname, kind: e.kind, path: e.path,
     live_lines: a.live_lines, mentioned: a.mentioned}) AS ents
OPTIONAL MATCH (newer:Decision)-[s:SUPERSEDES]->(d) WHERE newer.status <> 'rejected'
WITH d, srcs, issues, commits, ents,
     collect(DISTINCT CASE WHEN newer IS NULL THEN null ELSE {id: newer.id, title: newer.title, date: newer.date,
             reason: s.reason, method: s.method} END) AS superseded_by
OPTIONAL MATCH (d)-[s2:SUPERSEDES]->(older:Decision)
WITH d, srcs, issues, commits, ents, superseded_by,
     collect(DISTINCT CASE WHEN older IS NULL THEN null ELSE {id: older.id, title: older.title, date: older.date,
             reason: s2.reason, method: s2.method} END) AS supersedes
OPTIONAL MATCH (d)-[r:REFINES]->(ref:Decision)
WITH d, srcs, issues, commits, ents, superseded_by, supersedes,
     collect(DISTINCT CASE WHEN ref IS NULL THEN null ELSE {id: ref.id, title: ref.title, date: ref.date} END) AS refines
// people: authors / reviewers / commenters of the sources + commit authors
OPTIONAL MATCH (p:Person)-[rel:AUTHORED|REVIEWED|COMMENTED]->(x)
  WHERE x IN srcs OR x IN commits OR x IN issues OR x = d
WITH d, srcs, issues, commits, ents, superseded_by, supersedes, refines,
     collect(DISTINCT {id: p.id, name: coalesce(p.login, p.name), login: p.login, url: p.url,
             last_active: p.last_active, role: type(rel), on: labels(x)[0]}) AS people
RETURN d {.id, .title, .decision, .rationale, .alternatives, .quote, .quote_verified, .status, .kind, .date,
          .epoch, .source_type, .source_ref, .source_url, .live_lines, .created_by, .reviewed_by, .inferred_from} AS d,
       [s IN srcs | {type: labels(s)[0], number: s.number, sha: s.sha, title: coalesce(s.title, s.subject, s.section),
                     url: s.url, date: coalesce(s.merged_at, s.date, s.created_at)}] AS sources,
       [i IN issues | {number: i.number, title: i.title, url: i.url, is_incident: i.is_incident,
                       date: i.created_at}] AS issues,
       [c IN commits | {sha: c.sha, short: c.short, subject: c.subject, url: c.url, date: c.date}][..8] AS commits,
       ents, superseded_by, supersedes, refines, people
"""


def decision_details(ids: list[str]) -> list[dict]:
    out = []
    for r in db.run(DECISION_DETAIL, ids=ids):
        d = r["d"]
        people = _rank_people(r["people"])
        d.update({
            "sources": r["sources"], "issues": r["issues"], "commits": sorted(r["commits"], key=lambda c: c["date"] or ""),
            "entities": [e for e in r["ents"] if e.get("id")],
            "superseded_by": [s for s in r["superseded_by"] if s], "supersedes": [s for s in r["supersedes"] if s],
            "refines": [s for s in r["refines"] if s], "people": people,
        })
        d["superseded"] = bool(d["superseded_by"])
        d["confidence"] = confidence.score({
            **d, "n_issues": len(d["issues"]), "has_incident": any(i.get("is_incident") for i in d["issues"]),
            "n_reviewers": len({p["id"] for p in people if "REVIEWED" in p["roles"]}),
        })
        out.append(d)
    return out


def _rank_people(rows: list[dict]) -> list[dict]:
    weight = {("AUTHORED", "Decision"): 4, ("AUTHORED", "PullRequest"): 3, ("AUTHORED", "Commit"): 2, ("REVIEWED", "PullRequest"): 2.5,
              ("COMMENTED", "PullRequest"): 1, ("AUTHORED", "Issue"): 1, ("COMMENTED", "Issue"): 0.5}
    agg: dict[str, dict] = {}
    now = time.time()
    for p in rows:
        if not p.get("id") or (p.get("login") or "").lower() in ("ghost", "") and not p.get("name"):
            continue
        a = agg.setdefault(p["id"], {**{k: p[k] for k in ("id", "name", "login", "url", "last_active")},
                                     "roles": [], "score": 0.0})
        role = p["role"]
        if role not in a["roles"]:
            a["roles"].append(role)
        a["score"] += weight.get((role, p["on"]), 0.5)
    for a in agg.values():
        years_idle = max(0.0, (now - (a["last_active"] or 0)) / 31_557_600)
        a["active_recently"] = years_idle < 1.0
        a["score"] = round(a["score"] * (1.0 if years_idle < 1 else 0.6 if years_idle < 3 else 0.3), 2)
    return sorted(agg.values(), key=lambda a: -a["score"])[:6]


def _entity_fallback(entities: list[dict]) -> dict:
    """When there is no decision: show who/what touched the code so the user knows where to look."""
    if not entities:
        return {"commits": [], "people": []}
    ids = [e["id"] for e in entities]
    commits = db.run(
        """MATCH (c:Commit)-[m:MODIFIED]->(e:CodeEntity) WHERE e.id IN $ids AND NOT c.formatting
           OPTIONAL MATCH (c)-[:PART_OF]->(p:PullRequest)
           RETURN c.short AS short, c.subject AS subject, c.url AS url, c.date AS date, p.number AS pr,
                  c.epoch AS epoch, sum(m.lines) AS lines ORDER BY epoch DESC LIMIT 6""", ids=ids)
    people = db.run(
        """MATCH (c:Commit)-[o:OWNS_LINES]->(e:CodeEntity) WHERE e.id IN $ids
           MATCH (p:Person)-[:AUTHORED]->(c)
           RETURN coalesce(p.login, p.name) AS name, p.url AS url, p.last_active AS last_active,
                  sum(o.lines) AS lines ORDER BY lines DESC LIMIT 4""", ids=ids)
    return {"commits": commits, "people": people}


ANSWER_SYSTEM = """You answer "why is the code like this?" questions about the {repo} repository for a developer
who is new to the codebase. You may ONLY use the numbered evidence provided. Rules:
- Cite evidence inline as [D1], [D2] ... Every factual sentence needs a citation.
- If the most relevant decision was SUPERSEDED, say so clearly and explain the current (newer) reasoning first.
- If a decision's status is "inferred", say the reason is inferred and unverified.
- Mention when the decision was made (year) and who to ask, using the people listed.
- If the evidence does not actually answer the question, set "insufficient": true and explain what is missing.
- Be concise: 2-5 sentences. Plain language, markdown allowed (inline code for identifiers).
Output JSON only: {{"answer": "...", "used": ["D1"], "insufficient": false}}"""


def _evidence_block(decisions: list[dict]) -> str:
    parts = []
    for k, d in enumerate(decisions, 1):
        src = d["sources"][0] if d["sources"] else {}
        who = ", ".join(f"{p['name']} ({'/'.join(r.lower() for r in p['roles'])}"
                        f"{', inactive' if not p['active_recently'] else ''})" for p in d["people"][:3])
        sup = "; ".join(f"SUPERSEDED BY \"{s['title']}\" ({(s['date'] or '')[:10]}): {s['reason']}" for s in d["superseded_by"])
        parts.append(
            f"[D{k}] status={d['status']} confidence={d['confidence']['level']} date={(d['date'] or 'n/a')[:10]}\n"
            f"Title: {d['title']}\nDecision: {d['decision']}\nRationale: {d['rationale']}\n"
            f"Quote: \"{d.get('quote') or ''}\"\nSource: {src.get('type', '')} {src.get('title', '')}\n"
            f"Code: {', '.join(e['qualname'] for e in d['entities'][:5])}\nPeople: {who or 'unknown'}\n"
            + (f"{sup}\n" if sup else "")
        )
    return "\n".join(parts)


def _template_answer(d: dict) -> str:
    year = (d.get("date") or "")[:4]
    s = f"**{d['title']}.** {d['decision']} {d['rationale']} [D1]"
    if year:
        s += f" This was decided in {year}."
    if d["people"]:
        s += f" Best person to ask: {d['people'][0]['name']}."
    return s


def _graph(question: str, entities: list[dict], decisions: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(id_: str, type_: str, label: str, **extra):
        nodes.setdefault(id_, {"id": id_, "type": type_, "label": label, **extra})

    node("q", "question", question[:60])
    for e in entities:
        node(e["id"], "entity", e["qualname"], kind=e["kind"])
        edges.append({"source": "q", "target": e["id"], "type": "ABOUT"})
    for k, d in enumerate(decisions, 1):
        did = d["id"]
        node(did, "decision", d["title"], status=d["status"], superseded=d["superseded"], cite=f"D{k}",
             level=d["confidence"]["level"])
        linked = False
        for e in d["entities"]:
            if e["id"] in nodes:
                edges.append({"source": did, "target": e["id"], "type": "AFFECTS"})
                linked = True
        if not linked:
            edges.append({"source": "q", "target": did, "type": "SIMILAR"})
        for s in d["sources"][:1]:
            sid = f"{s['type']}:{s.get('number') or s.get('sha') or s.get('title')}"
            label = (f"PR #{s['number']}" if s["type"] == "PullRequest" else
                     f"Commit {(s.get('sha') or '')[:7]}" if s["type"] == "Commit" else "design.rst")
            node(sid, "source", label, url=s.get("url"), title=s.get("title"))
            edges.append({"source": did, "target": sid, "type": "EXTRACTED_FROM"})
        for i in d["issues"][:3]:
            iid = f"issue:{i['number']}"
            node(iid, "issue", f"#{i['number']}", url=i.get("url"), title=i.get("title"), incident=i.get("is_incident"))
            edges.append({"source": did, "target": iid, "type": "MOTIVATED_BY"})
        for p in d["people"][:2]:
            pid = f"person:{p['id']}"
            node(pid, "person", p["name"] or "?", url=p.get("url"))
            edges.append({"source": pid, "target": did, "type": "/".join(p["roles"][:2])})
        for s in d["superseded_by"]:
            node(s["id"], "decision", s["title"], status="explicit", superseded=False)
            edges.append({"source": s["id"], "target": did, "type": "SUPERSEDES"})
    return {"nodes": list(nodes.values()), "edges": edges}


def _log_question(question: str, answered: bool, entities: list[dict], top_conf: int) -> None:
    db.run("""CREATE (q:Question {text: $t, asked_at: $now, answered: $a, top_confidence: $c, entity_ids: $ids})""",
           t=question[:500], now=int(time.time()), a=answered, c=top_conf, ids=[e["id"] for e in entities])


def ask(question: str, k: int = 5, generate: bool = True, log_question: bool = True) -> dict:
    t0 = time.time()
    qvec = embed_query(question)
    entities = _resolve_entities(question, qvec)
    ent_ids = [e["id"] for e in entities]

    cand: dict[str, dict] = {}
    # exact identifier matches are strong evidence; full-text / semantic entity matches are hints
    ent_weight = {e["id"]: 1.0 if e["match"] == "exact" else 0.45 for e in entities}
    if ent_ids:
        for r in db.run(
            """MATCH (d:Decision)-[a:AFFECTS]->(e:CodeEntity)
               WHERE e.id IN $ids AND d.status <> 'rejected'
               RETURN d.id AS id, e.id AS eid, CASE WHEN a.mentioned THEN 1.0 ELSE 0.7 END AS w""", ids=ent_ids):
            w = r["w"] * ent_weight.get(r["eid"], 0.45)
            c = cand.setdefault(r["id"], {"graph": 0.0, "vec": 0.0})
            c["graph"] = max(c["graph"], w)
        # one hop up: decisions on the enclosing class / config dict
        for r in db.run(
            """MATCH (p:CodeEntity)-[:CONTAINS]->(e:CodeEntity) WHERE e.id IN $ids AND p.kind <> 'module'
               MATCH (d:Decision)-[a:AFFECTS]->(p) WHERE d.status <> 'rejected' AND a.mentioned
               RETURN d.id AS id""", ids=ent_ids):
            cand.setdefault(r["id"], {"graph": 0.4, "vec": 0.0})
    for r in db.run(
        """CALL db.index.vector.queryNodes('decision_embedding', 12, $v) YIELD node, score
           WHERE node.status <> 'rejected'
           RETURN node.id AS id, score""", v=qvec):
        c = cand.setdefault(r["id"], {"graph": 0.0, "vec": 0.0})
        c["vec"] = r["score"]
    # vector scores for graph-only candidates
    if cand:
        for r in db.run(
            """MATCH (d:Decision) WHERE d.id IN $ids AND d.embedding IS NOT NULL
               RETURN d.id AS id, vector.similarity.cosine(d.embedding, $v) AS s""", ids=list(cand), v=qvec):
            cand[r["id"]]["vec"] = max(cand[r["id"]]["vec"], r["s"])

    relevant = {i: c for i, c in cand.items() if c["graph"] >= 0.7 or c["vec"] >= MIN_VEC}
    details = {d["id"]: d for d in decision_details(list(relevant))} if relevant else {}
    top_vec = max((c["vec"] for c in relevant.values()), default=0.0)
    span = max(top_vec - VEC_FLOOR, 0.05)
    for i, d in details.items():
        c = relevant[i]
        vn = min(max((c["vec"] - VEC_FLOOR) / span, 0.0), 1.0)
        d["relevance"] = round(0.55 * vn + 0.30 * c["graph"] + 0.15 * d["confidence"]["score"] / 100, 4)
        d["match"] = "graph+semantic" if c["graph"] >= 0.7 and c["vec"] >= MIN_VEC else "graph" if c["graph"] else "semantic"
    ranked = sorted(details.values(), key=lambda d: -d["relevance"])
    # A superseded decision is still useful context, but never alone: pull in what replaced it.
    top = ranked[:k]
    for d in list(top):
        for s in d["superseded_by"]:
            if s["id"] not in {x["id"] for x in top}:
                extra = details.get(s["id"]) or (decision_details([s["id"]]) or [None])[0]
                if extra:
                    extra.setdefault("relevance", d["relevance"])
                    extra.setdefault("match", "supersession")
                    top.append(extra)
    # ...and a replacement decision brings its predecessor along, so the answer can tell the whole story.
    for d in list(top[:3]):
        for s in d["supersedes"][:2]:
            if s["id"] not in {x["id"] for x in top}:
                older = details.get(s["id"]) or (decision_details([s["id"]]) or [None])[0]
                if older:
                    older.setdefault("relevance", round(d["relevance"] * 0.8, 4))
                    older.setdefault("match", "supersession")
                    top.append(older)
    top = sorted(top, key=lambda d: (d["superseded"], -d["relevance"]))[: k + 2]

    best = max((d["confidence"]["score"] for d in top if not d["superseded"]), default=0)
    missing = unknown_terms(question)
    insufficient = not top or best < 25 or bool(missing)
    answer, used = "", []

    if not insufficient and not generate:
        used = ["D1"]
    elif not insufficient:
        try:
            data = llm.generate_json(
                f"Question: {question}\n\nEvidence:\n{_evidence_block(top)}",
                system=ANSWER_SYSTEM.format(repo=REPO_SLUG), namespace="answer", temperature=0.2, max_rounds=2,
                models=ANSWER_MODELS, deadline_s=ANSWER_DEADLINE,
            )
            answer = data.get("answer", "")
            used = [u for u in data.get("used", []) if isinstance(u, str)]
            insufficient = bool(data.get("insufficient")) and not used
        except Exception as e:  # LLM down: degrade to a templated answer from the top decision
            log.warning("answer LLM failed: %s", e)
            first = next((d for d in top if not d["superseded"]), top[0])
            answer = _template_answer(first)
            used = ["D1"]

    if insufficient and missing:
        answer = (f"**No code and no recorded decision in this repository mentions {', '.join(f'`{m}`' for m in missing)}.** "
                  "WhyGraph only answers from the repository's own history, so it won't speculate about it.")
        used = []
    elif insufficient:
        answer = ("**No recorded decision explains this.** The graph has no PR discussion, issue, commit message or "
                  "design note giving a reason, so WhyGraph won't guess. Below is who and what last touched this "
                  "code; it has been flagged in the admin console as a documentation gap.")
        used = []

    overall = None
    cited = [top[int(u[1:]) - 1] for u in used if u[1:].isdigit() and 0 < int(u[1:]) <= len(top)]
    primary = next((d for d in cited if not d["superseded"]), cited[0] if cited else None)
    if primary and not insufficient:
        overall = primary["confidence"]
    if log_question:
        _log_question(question, not insufficient, entities, overall["score"] if overall else 0)

    return {
        "question": question,
        "answer": answer,
        "insufficient": insufficient,
        "confidence": overall or {"score": 0, "level": "insufficient", "factors": []},
        "entities": entities,
        "decisions": [{**d, "cite": f"D{n}"} for n, d in enumerate(top, 1)],
        "cited": used,
        "fallback": _entity_fallback(entities) if insufficient else None,
        "unknown_terms": missing,
        "graph": _graph(question, entities, top),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "asked_at": datetime.now(timezone.utc).isoformat(),
    }
