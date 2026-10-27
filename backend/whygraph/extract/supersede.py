"""Supersession: which decisions were later overridden?

1. revert   – a revert commit's decision supersedes the decisions of the reverted commit/PR (deterministic)
2. blame    – A and B touch the same entity, A's code is no longer live there but B's is -> candidate pair
3. explicit – the extractor saw "replaces #123" style references -> candidate pair
Candidate pairs are judged by the LLM (supersedes / refines / unrelated)."""
from __future__ import annotations

import logging
import re

from .. import db, llm
from ..config import REPO_SLUG

log = logging.getLogger(__name__)


def compute_liveness() -> None:
    """How many lines of each affected entity are still owned (git blame @ HEAD) by the decision's commits."""
    db.run("""MATCH (d:Decision)-[a:AFFECTS]->(e:CodeEntity)
              OPTIONAL MATCH (d)-[:IMPLEMENTED_BY]->(c:Commit)-[o:OWNS_LINES]->(e)
              WITH d, a, sum(o.lines) AS live, count(c) AS n
              SET a.live_lines = CASE WHEN EXISTS { (d)-[:IMPLEMENTED_BY]->() } THEN live ELSE null END""")
    db.run("""MATCH (d:Decision)
              OPTIONAL MATCH (d)-[a:AFFECTS]->()
              WITH d, sum(a.live_lines) AS live, count(a.live_lines) AS n
              SET d.live_lines = CASE WHEN n = 0 THEN null ELSE live END""")


def revert_edges() -> int:
    rows = db.run(
        """MATCH (rd:Decision {kind: 'revert'})-[:IMPLEMENTED_BY]->(r:Commit)-[:REVERTS]->(t:Commit)
           MATCH (d:Decision)-[:IMPLEMENTED_BY]->(t) WHERE d <> rd
           MERGE (rd)-[s:SUPERSEDES]->(d) SET s.method = 'revert', s.reason = 'Reverted by commit ' + r.short
           RETURN count(*) AS n""")
    rows2 = db.run(
        """MATCH (rd:Decision {kind: 'revert'})-[:IMPLEMENTED_BY]->(r:Commit)-[:REVERTS]->(t:Commit)-[:PART_OF]->(p:PullRequest)
           MATCH (d:Decision)-[:EXTRACTED_FROM]->(p) WHERE d <> rd
           MERGE (rd)-[s:SUPERSEDES]->(d) SET s.method = 'revert', s.reason = 'Reverted by commit ' + r.short
           RETURN count(*) AS n""")
    return rows[0]["n"] + rows2[0]["n"]


def candidate_pairs(limit: int) -> list[dict]:
    blame = db.run(
        """MATCH (a:Decision)-[ra:AFFECTS]->(e:CodeEntity)<-[rb:AFFECTS]-(b:Decision)
           WHERE a.epoch < b.epoch AND a.kind <> 'revert' AND b.kind <> 'revert'
             AND a.status <> 'rejected' AND b.status <> 'rejected'
             AND ra.live_lines = 0 AND coalesce(rb.live_lines, 0) > 0
             AND (ra.mentioned OR coalesce(ra.lines, 0) >= 3) AND (rb.mentioned OR coalesce(rb.lines, 0) >= 3)
             AND NOT (b)-[:SUPERSEDES|REFINES|UNRELATED_TO]->(a)
           WITH a, b, collect(e.qualname)[..3] AS ents, count(e) AS shared
           RETURN a.id AS a, b.id AS b, ents, 'blame' AS method, shared
           ORDER BY shared DESC LIMIT $limit""",
        limit=limit,
    )
    hinted = []
    for r in db.run("""MATCH (b:Decision) WHERE b.supersedes_hint IS NOT NULL AND b.supersedes_hint <> ''
                       RETURN b.id AS b, b.supersedes_hint AS hint"""):
        for num in re.findall(r"#(\d+)", r["hint"]):
            for a in db.run("""MATCH (a:Decision)-[:EXTRACTED_FROM]->(p:PullRequest {number: $n})
                               MATCH (b:Decision {id: $b}) WHERE a <> b
                                 AND NOT (b)-[:SUPERSEDES|REFINES|UNRELATED_TO]->(a)
                               RETURN a.id AS a""", n=int(num), b=r["b"]):
                hinted.append({"a": a["a"], "b": r["b"], "ents": [], "method": "explicit"})
    seen, out = set(), []
    for p in hinted + blame:
        if (p["a"], p["b"]) not in seen:
            seen.add((p["a"], p["b"]))
            out.append(p)
    return out[:limit]


SYSTEM = """You compare two design decisions from the {repo} repository. Decision A is older, decision B is newer.
Decide their relation:
- "supersedes": B replaces, reverses or overrides A, so A no longer describes how the code works.
- "refines": B adjusts or extends A but A's core idea still holds.
- "unrelated": they are about different things.
Output JSON only."""

PROMPT = """Return JSON: {{"verdicts": [{{"pair": <n>, "relation": "supersedes|refines|unrelated", "reason": "one sentence"}}]}}

{pairs}"""


def judge(limit: int = 120, per_call: int = 8) -> int:
    pairs = candidate_pairs(limit)
    log.info("Judging %d candidate supersession pairs", len(pairs))
    if not pairs:
        return 0
    ids = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
    info = {r["id"]: r for r in db.run(
        """MATCH (d:Decision) WHERE d.id IN $ids
           RETURN d.id AS id, d.title AS title, d.decision AS decision, d.rationale AS rationale, d.date AS date""",
        ids=ids)}
    made = 0
    for i in range(0, len(pairs), per_call):
        group = pairs[i : i + per_call]
        text = []
        for k, p in enumerate(group):
            a, b = info[p["a"]], info[p["b"]]
            text.append(f"PAIR {k} (shared code: {', '.join(p['ents']) or 'n/a'})\n"
                        f"A ({(a['date'] or '')[:10]}): {a['title']} — {a['decision']} Because: {a['rationale']}\n"
                        f"B ({(b['date'] or '')[:10]}): {b['title']} — {b['decision']} Because: {b['rationale']}")
        data = llm.generate_json(PROMPT.format(pairs="\n\n".join(text)), system=SYSTEM.format(repo=REPO_SLUG),
                                 namespace="supersede")
        for v in (data.get("verdicts") or []) if isinstance(data, dict) else []:
            try:
                p = group[int(v.get("pair"))]
            except (TypeError, ValueError, IndexError):
                continue
            rel = {"supersedes": "SUPERSEDES", "refines": "REFINES"}.get(v.get("relation"), "UNRELATED_TO")
            db.run(f"""MATCH (a:Decision {{id: $a}}), (b:Decision {{id: $b}})
                       MERGE (b)-[s:{rel}]->(a) SET s.method = $method, s.reason = $reason""",
                   a=p["a"], b=p["b"], method=p["method"] + "+llm", reason=(v.get("reason") or "")[:300])
            made += rel == "SUPERSEDES"
    log.info("%d supersession edges from LLM judging", made)
    return made


def run(use_llm: bool = True) -> None:
    compute_liveness()
    n = revert_edges()
    log.info("%d revert supersession edges", n)
    if use_llm:
        judge()
    db.run("MATCH (d:Decision) SET d.superseded = EXISTS { (:Decision)-[:SUPERSEDES]->(d) }")
