"""Admin console: review AI-inferred decisions, author decisions, and surface knowledge gaps."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from . import db
from .extract.decisions import link_entities
from .extract.embed_nodes import embed_one_decision
from .extract.supersede import compute_liveness
from .query.ask import decision_details


def review_queue(limit: int = 100) -> list[dict]:
    ids = [r["id"] for r in db.run(
        """MATCH (d:Decision {status: 'inferred'}) WHERE d.kind <> 'revert'
           OPTIONAL MATCH (d)-[:AFFECTS]->(e:CodeEntity)
           WITH d, max(e.churn) AS churn
           RETURN d.id AS id ORDER BY coalesce(d.inferred_from, '') = 'code' DESC, coalesce(churn, 0) DESC
           LIMIT $limit""", limit=limit)]
    order = {i: n for n, i in enumerate(ids)}
    return sorted(decision_details(ids), key=lambda d: order[d["id"]])


def review(decision_id: str, action: str, reviewer: str, fields: dict) -> dict:
    now = int(time.time())
    if action == "reject":
        db.run("""MATCH (d:Decision {id: $id}) SET d.status = 'rejected', d.reviewed_by = $who, d.reviewed_at = $now""",
               id=decision_id, who=reviewer, now=now)
    elif action in ("confirm", "edit"):
        allowed = {k: v for k, v in fields.items() if k in ("title", "decision", "rationale") and v}
        db.run("""MATCH (d:Decision {id: $id})
                  SET d += $f, d.status = 'confirmed', d.reviewed_by = $who, d.reviewed_at = $now""",
               id=decision_id, f=allowed, who=reviewer, now=now)
        embed_one_decision(decision_id)
    else:
        raise ValueError("action must be confirm, edit or reject")
    db.run("MATCH (d:Decision) SET d.superseded = EXISTS { (n:Decision)-[:SUPERSEDES]->(d) WHERE n.status <> 'rejected' }")
    return decision_details([decision_id])[0]


def author_decision(payload: dict) -> dict:
    now = datetime.now(timezone.utc)
    slug = re.sub(r"[^a-z0-9]+", "-", payload["title"].lower()).strip("-")[:40]
    did = f"human:{int(now.timestamp())}:{slug}"
    author = payload.get("author") or "maintainer"
    db.run("""CREATE (d:Decision {id: $id, title: $title, decision: $decision, rationale: $rationale,
                                   alternatives: $alternatives, quote: $rationale, quote_verified: true,
                                   status: 'authored', kind: $kind, date: $date, epoch: $epoch,
                                   source_type: 'human', source_ref: $author, created_by: $author})""",
           id=did, title=payload["title"][:120], decision=payload["decision"][:800],
           rationale=payload.get("rationale", "")[:1500], alternatives=payload.get("alternatives") or [],
           kind=payload.get("kind") or "design", date=now.isoformat(), epoch=int(now.timestamp()), author=author)
    db.run("""MERGE (p:Person {id: $pid}) ON CREATE SET p.name = $author
              WITH p MATCH (d:Decision {id: $id}) MERGE (p)-[:AUTHORED]->(d)""",
           pid=f"admin:{author.lower()}", author=author, id=did)
    if payload.get("entity_ids"):
        db.run("""MATCH (d:Decision {id: $id}) MATCH (e:CodeEntity) WHERE e.id IN $eids
                  MERGE (d)-[a:AFFECTS]->(e) SET a.mentioned = true""", id=did, eids=payload["entity_ids"])
    else:
        link_entities(did, payload.get("entity_names") or [], restrict_to_modified=False)
    for old in payload.get("supersedes") or []:
        db.run("""MATCH (n:Decision {id: $id}), (o:Decision {id: $old})
                  MERGE (n)-[s:SUPERSEDES]->(o) SET s.method = 'human', s.reason = 'Marked by ' + $author""",
               id=did, old=old, author=author)
    # Unanswered questions about these entities are now answerable.
    if payload.get("entity_ids"):
        db.run("""MATCH (q:Question {answered: false}) WHERE any(x IN q.entity_ids WHERE x IN $eids)
                  SET q.resolved_by = $id""", eids=payload["entity_ids"], id=did)
    compute_liveness()
    db.run("MATCH (d:Decision) SET d.superseded = EXISTS { (n:Decision)-[:SUPERSEDES]->(d) WHERE n.status <> 'rejected' }")
    embed_one_decision(did)
    return decision_details([did])[0]


def gaps() -> dict:
    stats = db.run(
        """MATCH (e:CodeEntity) WHERE e.alive AND e.kind <> 'module'
           WITH count(e) AS total,
                count(CASE WHEN EXISTS { MATCH (d:Decision)-[:AFFECTS]->(e)
                      WHERE d.status IN ['explicit','confirmed','authored'] } THEN 1 END) AS documented,
                count(CASE WHEN e.churn >= 3 THEN 1 END) AS busy,
                count(CASE WHEN e.churn >= 3 AND EXISTS { MATCH (d:Decision)-[:AFFECTS]->(e)
                      WHERE d.status IN ['explicit','confirmed','authored'] } THEN 1 END) AS busy_documented
           RETURN total, documented, busy, busy_documented""")[0]
    by_status = {r["s"]: r["n"] for r in db.run("MATCH (d:Decision) RETURN d.status AS s, count(*) AS n")}
    hotspots = db.run(
        """MATCH (e:CodeEntity) WHERE e.alive AND e.kind <> 'module' AND e.churn >= 3
             AND NOT EXISTS { MATCH (d:Decision)-[:AFFECTS]->(e) WHERE d.status IN ['explicit','confirmed','authored'] }
           OPTIONAL MATCH (inf:Decision {status: 'inferred'})-[:AFFECTS]->(e)
           RETURN e.id AS id, e.qualname AS qualname, e.kind AS kind, e.path AS path, e.churn AS churn,
                  e.author_count AS authors, e.last_modified AS last_modified, count(inf) > 0 AS has_inferred
           ORDER BY e.churn DESC LIMIT 40""")
    concentration = db.run(
        """MATCH (c:Commit)-[o:OWNS_LINES]->(e:CodeEntity) WHERE e.alive AND e.kind IN ['class','function','method','config']
           MATCH (p:Person)-[:AUTHORED]->(c)
           WITH e, p, sum(o.lines) AS lines
           WITH e, collect({p: p, lines: lines}) AS owners, sum(lines) AS total
           WHERE total >= 15
           UNWIND owners AS ow
           WITH e, total, ow ORDER BY ow.lines DESC
           WITH e, total, collect(ow)[0] AS top
           WITH e, total, top, toFloat(top.lines) / total AS share
           WHERE share >= 0.8
           RETURN e.id AS id, e.qualname AS qualname, e.kind AS kind, e.path AS path, total AS lines,
                  round(share * 100) AS share, coalesce(top.p.login, top.p.name) AS owner,
                  top.p.last_active AS owner_last_active
           ORDER BY lines DESC LIMIT 30""")
    silent = db.run(
        """MATCH (c:Commit)-[m:MODIFIED]->(e:CodeEntity)
           WHERE NOT c.is_merge AND NOT c.formatting AND NOT c.trivial AND NOT (c)-[:PART_OF]->(:PullRequest)
             AND NOT (c)-[:REFERENCES]->(:Issue) AND size(c.message) < 80
             AND NOT EXISTS { (:Decision)-[:IMPLEMENTED_BY]->(c) }
           WITH c, sum(m.lines) AS lines, collect(DISTINCT e.qualname)[..4] AS ents
           WHERE lines >= 25
           OPTIONAL MATCH (p:Person)-[:AUTHORED]->(c)
           RETURN c.short AS short, c.subject AS subject, c.url AS url, c.date AS date, lines, ents,
                  coalesce(p.login, p.name) AS author
           ORDER BY c.epoch DESC LIMIT 25""")
    unanswered = db.run(
        """MATCH (q:Question {answered: false}) WHERE q.resolved_by IS NULL
           OPTIONAL MATCH (e:CodeEntity) WHERE e.id IN q.entity_ids
           RETURN q.text AS text, q.asked_at AS asked_at, collect(e {.id, .qualname}) AS entities
           ORDER BY q.asked_at DESC LIMIT 25""")
    questions = db.run("""MATCH (q:Question) RETURN count(q) AS total,
                          count(CASE WHEN q.answered THEN 1 END) AS answered""")[0]
    return {
        "stats": {**stats, "decisions": by_status, "questions": questions,
                  "coverage": round(100 * stats["busy_documented"] / max(stats["busy"], 1))},
        "hotspots": hotspots, "concentration": concentration, "silent_commits": silent, "unanswered": unanswered,
    }
