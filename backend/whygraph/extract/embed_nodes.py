"""Attach local embeddings to Decision and CodeEntity nodes that lack one."""
from __future__ import annotations

import logging

from .. import db
from ..embed import embed_texts

log = logging.getLogger(__name__)


def decision_text(d: dict) -> str:
    ents = ", ".join(d.get("entities") or [])
    return f"{d['title']}. {d.get('decision') or ''} Why: {d.get('rationale') or ''} Code: {ents}"


def run() -> None:
    rows = db.run("""MATCH (d:Decision) WHERE d.embedding IS NULL
                     OPTIONAL MATCH (d)-[:AFFECTS]->(e:CodeEntity)
                     RETURN d.id AS id, d.title AS title, d.decision AS decision, d.rationale AS rationale,
                            collect(e.qualname)[..8] AS entities""")
    if rows:
        vecs = embed_texts([decision_text(r) for r in rows])
        db.run_batched("UNWIND $rows AS r MATCH (d:Decision {id: r.id}) SET d.embedding = r.v",
                       [{"id": r["id"], "v": v} for r, v in zip(rows, vecs)], batch=200)
    log.info("Embedded %d decisions", len(rows))

    ents = db.run("""MATCH (e:CodeEntity) WHERE e.embedding IS NULL AND e.alive
                     RETURN e.id AS id, e.kind AS kind, e.qualname AS q, e.path AS path, e.doc AS doc,
                            e.signature AS sig""")
    if ents:
        texts = [f"{e['kind']} {e['q'].replace('config:', 'config key ')} in {e['path']}. {e['sig'] or ''} {e['doc'] or ''}"
                 for e in ents]
        vecs = embed_texts(texts)
        db.run_batched("UNWIND $rows AS r MATCH (e:CodeEntity {id: r.id}) SET e.embedding = r.v",
                       [{"id": e["id"], "v": v} for e, v in zip(ents, vecs)], batch=200)
    log.info("Embedded %d code entities", len(ents))


def embed_one_decision(decision_id: str) -> None:
    db.run("MATCH (d:Decision {id: $id}) SET d.embedding = null", id=decision_id)
    run()
