"""For busy code that has no recorded decision, ask the LLM to infer the most likely reason from the code and the
commit that introduced it. Results are status='inferred' and go to the admin review queue."""
from __future__ import annotations

import logging
import subprocess

from .. import db, llm
from ..config import REPO_PATH, REPO_SLUG
from .decisions import _write

log = logging.getLogger(__name__)

SYSTEM = """You are a senior engineer reviewing the {repo} codebase. For each code entity you get its current code and
the commit that wrote most of its live lines. Infer the MOST LIKELY reason the code is the way it is.
Be honest about uncertainty: write the rationale as a hypothesis ("Likely because ..."), and never invent
issue numbers, people or dates. If nothing sensible can be inferred, return "decision": null for it.
Output JSON only."""

PROMPT = """Return JSON: {{"results": [{{"entity_id": "<id>", "title": "<= 10 words", "decision": "what the code does
deliberately, 1 sentence", "rationale": "Likely because ... (1-2 sentences)", "kind": "design|default|api|compat|security|performance|bugfix"}}]}}

{items}"""


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_PATH, capture_output=True, text=True, errors="replace").stdout


def _current_code(e: dict) -> str:
    real = e["path"] if (REPO_PATH / e["path"]).exists() else f"src/{e['path']}"
    try:
        lines = (REPO_PATH / real).read_text().splitlines()
    except OSError:
        return ""
    s, t = e["start_line"] - 1, min(e["end_line"], e["start_line"] + 50)
    return "\n".join(lines[s:t])


def candidates(limit: int) -> list[dict]:
    return db.run(
        """MATCH (e:CodeEntity)
           WHERE e.alive AND e.kind IN ['config','function','method','class','attribute','constant']
             AND e.churn >= 3
             AND NOT EXISTS { MATCH (d:Decision)-[:AFFECTS]->(e) WHERE d.status IN ['explicit','confirmed','authored'] }
             AND NOT EXISTS { MATCH (d:Decision {inferred_from: 'code'})-[:AFFECTS]->(e) }
             AND NOT EXISTS { MATCH (x:ExtractionDone {sid: 'infer:' + e.id}) }
           MATCH (c:Commit)-[o:OWNS_LINES]->(e) WHERE NOT c.formatting
           WITH e, c, o ORDER BY o.lines DESC
           WITH e, collect(c)[0] AS c
           RETURN e.id AS id, e.qualname AS qualname, e.kind AS kind, e.path AS path, e.start_line AS start_line,
                  e.end_line AS end_line, e.churn AS churn, c.sha AS sha, c.message AS message, c.date AS date
           ORDER BY e.churn DESC LIMIT $limit""",
        limit=limit,
    )


def run(limit: int = 40, per_call: int = 6) -> int:
    ents = candidates(limit)
    log.info("Inferring decisions for %d undocumented hotspots", len(ents))
    made = 0
    for i in range(0, len(ents), per_call):
        group = ents[i : i + per_call]
        items = []
        for e in group:
            diff = _git("show", "--format=", "-U2", e["sha"], "--", e["path"], f"src/{e['path']}")[:2200]
            items.append(
                f"ENTITY {e['id']} ({e['kind']} {e['qualname']})\n--- current code ---\n{_current_code(e)[:2500]}\n"
                f"--- commit {e['sha'][:8]} ({(e['date'] or '')[:10]}) message ---\n{(e['message'] or '')[:800]}\n"
                f"--- diff excerpt ---\n{diff}"
            )
        data = llm.generate_json(PROMPT.format(items="\n\n=====\n\n".join(items)),
                                 system=SYSTEM.format(repo=REPO_SLUG), namespace="infer")
        by_id = {r.get("entity_id"): r for r in (data.get("results") or [])} if isinstance(data, dict) else {}
        rows = []
        for e in group:
            r = by_id.get(e["id"])
            if not r or not r.get("decision"):
                db.run("MERGE (:ExtractionDone {sid: $sid})", sid=f"infer:{e['id']}")
                continue
            rows.append({
                "id": f"infer:{e['id']}", "title": r.get("title", "")[:120], "decision": r["decision"][:600],
                "rationale": (r.get("rationale") or "")[:900], "alternatives": [], "quote": "",
                "quote_verified": False, "status": "inferred", "inferred_from": "code",
                "kind": (r.get("kind") or "design")[:20], "entities": [], "supersedes_hint": None,
                "date": e["date"], "epoch": None, "source_type": "commit", "source_ref": e["sha"][:12],
                "source_url": f"https://github.com/{REPO_SLUG}/commit/{e['sha']}",
            })
        if rows:
            _write(rows)
            # pin the inferred decision to exactly its entity (not everything the commit touched)
            for row, e in zip(rows, [e for e in group if by_id.get(e["id"], {}).get("decision")]):
                db.run("""MATCH (d:Decision {id: $did})-[a:AFFECTS]->(x:CodeEntity) WHERE x.id <> $eid DELETE a""",
                       did=row["id"], eid=e["id"])
                db.run("""MATCH (d:Decision {id: $did}), (x:CodeEntity {id: $eid})
                          MERGE (d)-[a:AFFECTS]->(x) SET a.mentioned = true""", did=row["id"], eid=e["id"])
                db.run("MATCH (d:Decision {id: $did}) SET d.epoch = $ep", did=row["id"],
                       ep=db.run("MATCH (c:Commit) WHERE c.sha STARTS WITH $s RETURN c.epoch AS e",
                                 s=row["source_ref"])[0]["e"])
        made += len(rows)
        log.info("inferred %d (total %d)", len(rows), made)
    return made
