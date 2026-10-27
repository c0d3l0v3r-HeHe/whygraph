"""Offline evaluation of retrieval, supersession and refusal (no LLM calls; retrieval-only mode).

    uv run python -m whygraph.eval

1. Retrieval: for explicit decisions that name a live code entity, ask "Why does `<entity>` ...?" and check whether the
   source decision is in the top-1 / top-3 results.
2. Supersession: for every superseded decision, ask about the entity it affects and check that the answer set marks
   it superseded and includes the decision that replaced it.
3. Refusal: questions about things Flask doesn't contain must come back "insufficient".
"""
from __future__ import annotations

import json
import random

from . import db
from .config import DATA_DIR
from .query.ask import ask

OUT_OF_SCOPE = [
    "Why does Flask use Kubernetes operators for routing?",
    "Why is the GraphQL resolver cache limited to 50 entries?",
    "Why does the payment gateway retry three times?",
    "Why does `TensorScheduler.allocate` pin GPUs?",
    "Why is the Kafka consumer group named flask-workers?",
    "Why does Flask store sessions in MongoDB by default?",
]


def retrieval_cases(n: int = 40) -> list[dict]:
    rows = db.run(
        """MATCH (d:Decision {status: 'explicit'})-[a:AFFECTS {mentioned: true}]->(e:CodeEntity)
           WHERE e.alive AND e.kind <> 'module' AND NOT d.superseded AND d.source_type IN ['pr', 'commit']
           WITH d, e ORDER BY e.churn DESC
           WITH d, collect(e)[0] AS e
           RETURN d.id AS id, d.title AS title, e.qualname AS q, e.kind AS kind""")
    random.Random(7).shuffle(rows)
    return rows[:n]


def supersession_cases() -> list[dict]:
    return db.run(
        """MATCH (n:Decision)-[:SUPERSEDES]->(d:Decision)-[:AFFECTS {mentioned: true}]->(e:CodeEntity)
           WHERE e.alive AND e.kind <> 'module' AND n.status <> 'rejected'
           WITH d, n, collect(e)[0] AS e
           RETURN d.id AS old, n.id AS new, e.qualname AS q, d.title AS title LIMIT 25""")


def question_for(q: str, kind: str = "") -> str:
    name = q.replace("config:", "")
    return f"Why is the {name} config set like this?" if kind == "config" else f"Why does `{name}` work like this?"


def main() -> None:
    report: dict = {}

    cases = retrieval_cases()
    hit1 = hit3 = cov = 0
    misses = []
    for c in cases:
        # specific: the user describes the behaviour they are puzzled by
        q = f"{c['title']}: why was that done in `{c['q'].replace('config:', '')}`?"
        res = ask(q, k=5, generate=False, log_question=False)
        ids = [d["id"] for d in res["decisions"]]
        hit1 += ids[:1] == [c["id"]]
        hit3 += c["id"] in ids[:3]
        if c["id"] not in ids[:3]:
            misses.append({"q": q, "expected": c["title"], "got": [d["title"] for d in res["decisions"][:3]]})
        # broad: "why is X like this?" has many valid answers; is the decision among the 7 shown?
        broad = ask(question_for(c["q"], c["kind"]), k=7, generate=False, log_question=False)
        cov += c["id"] in [d["id"] for d in broad["decisions"]]
    n = max(len(cases), 1)
    report["retrieval"] = {"cases": len(cases), "specific_hit@1": round(hit1 / n, 3),
                           "specific_hit@3": round(hit3 / n, 3), "broad_coverage@7": round(cov / n, 3),
                           "misses": misses[:10]}

    sup = supersession_cases()
    returned = flagged = with_new = 0
    for c in sup:
        res = ask(question_for(c["q"]), k=6, generate=False, log_question=False)
        by_id = {d["id"]: d for d in res["decisions"]}
        if c["old"] in by_id:
            returned += 1
            flagged += by_id[c["old"]]["superseded"]
        with_new += c["new"] in by_id
    report["supersession"] = {"cases": len(sup), "old_decision_returned": returned,
                              "flagged_superseded_when_returned": f"{flagged}/{returned}",
                              "replacement_included": round(with_new / max(len(sup), 1), 3)}

    refused = 0
    for q in OUT_OF_SCOPE:
        res = ask(q, generate=False, log_question=False)
        refused += res["insufficient"]
    report["refusal"] = {"cases": len(OUT_OF_SCOPE), "refused": refused,
                         "rate": round(refused / len(OUT_OF_SCOPE), 3)}

    (DATA_DIR / "eval.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "misses"} for k, v in report.items()}, indent=2))


if __name__ == "__main__":
    main()
