"""Pipeline CLI.

    uv run python -m whygraph.cli all            # everything, resumable
    uv run python -m whygraph.cli git|github|load|extract|infer|supersede|embed|status
    uv run python -m whygraph.cli ask "why is MAX_COOKIE_SIZE 4093?"
"""
from __future__ import annotations

import argparse
import json
import logging

from . import db


def main() -> None:
    ap = argparse.ArgumentParser(prog="whygraph")
    ap.add_argument("step", choices=["git", "github", "load", "extract", "infer", "supersede", "embed", "all",
                                     "status", "ask"])
    ap.add_argument("text", nargs="?")
    ap.add_argument("--wipe", action="store_true", help="wipe the graph before loading")
    ap.add_argument("--prs", type=int, default=400, help="max PRs to send to the LLM")
    ap.add_argument("--commits", type=int, default=120, help="max PR-less commits to send to the LLM")
    ap.add_argument("--infer", type=int, default=40, help="max hotspots to infer decisions for")
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "neo4j", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from .extract import decisions, embed_nodes, infer, supersede
    from .ingest import git_walk, github_fetch
    from . import load

    steps = {
        "git": git_walk.run,
        "github": github_fetch.run,
        "load": lambda: load.run(wipe=a.wipe),
        "extract": lambda: (decisions.revert_decisions(),
                            None if a.no_llm else decisions.extract_explicit(a.prs, a.commits)),
        "infer": lambda: None if a.no_llm else infer.run(a.infer),
        "supersede": lambda: supersede.run(use_llm=not a.no_llm),
        "embed": embed_nodes.run,
    }
    if a.step == "all":
        for s in ["git", "github", "load", "extract", "infer", "supersede", "embed"]:
            logging.info("=== %s ===", s)
            steps[s]()
    elif a.step == "status":
        q = """CALL () { MATCH (n:CodeEntity) RETURN 'entities' AS k, count(n) AS v
               UNION ALL MATCH (n:Commit) RETURN 'commits' AS k, count(n) AS v
               UNION ALL MATCH (n:PullRequest) RETURN 'prs' AS k, count(n) AS v
               UNION ALL MATCH (n:Issue) RETURN 'issues' AS k, count(n) AS v
               UNION ALL MATCH (n:Person) RETURN 'people' AS k, count(n) AS v
               UNION ALL MATCH (n:Decision) RETURN 'decisions:' + n.status AS k, count(n) AS v
               UNION ALL MATCH ()-[r:SUPERSEDES]->() RETURN 'supersedes' AS k, count(r) AS v }
               RETURN k, v"""
        for r in db.run(q):
            print(f"{r['k']:>24}  {r['v']}")
    elif a.step == "ask":
        from .query.ask import ask
        res = ask(a.text or "")
        print(res["answer"])
        print(json.dumps(res["confidence"], indent=1))
        for d in res["decisions"]:
            print(f" {d['cite']} [{d['status']}/{d['confidence']['level']}{' SUPERSEDED' if d['superseded'] else ''}]"
                  f" {d['title']} ({(d['date'] or '')[:10]}) rel={d['relevance']}")
    else:
        steps[a.step]()


if __name__ == "__main__":
    main()
