# WhyGraph — *why is the code like this?*

> hackFront India 2026 · AI & Developer Tools · Problem 01 "Why The Code Is Like This" · Neo4j track

Developers can read code but not intent. WhyGraph ingests a repository's full history (commits, pull-request
discussions, review comments, issues and design docs) into a **Neo4j knowledge graph**. It then answers
natural-language "why" questions with an **evidence chain**: the decision, the discussion that produced it, the
person to ask, and the date. It **detects when a decision was later overridden**, scores confidence from **facts in
the graph** rather than from the LLM, and **refuses to guess** when the graph has no answer.

Demo repository: [`pallets/flask`](https://github.com/pallets/flask): 5,562 commits (2010–2026), 1,634 merged PRs,
2,768 issues.

---

## Why not "vector search over docs"?

| Failure of plain RAG | What WhyGraph does instead |
|---|---|
| Returns text that *mentions* the topic, not the decision that *governs* it | Questions are first resolved to **code entities** (tree-sitter parsed functions, classes, attributes, config keys), then the graph is walked from code → commits → PR → decision |
| Docs drift; commits & PRs keep telling the truth | Decisions are extracted from PRs, reviews, issues and commit messages, each with a **verbatim quote that is verified** against the source |
| A reversed decision still looks authoritative | **Supersession detection**: revert commits, `git blame` liveness (is this decision's code still at HEAD?), explicit "replaces #123" references, and an LLM judge on candidate pairs |
| Nobody links incidents to the code they changed | Issues labelled or titled as bugs/regressions become incident evidence; `fixes #N` links PRs/commits to them |
| LLMs make things up | Confidence is computed from graph facts. Below a threshold the system answers "no recorded decision" and flags the gap |

## Architecture

```
               ┌────────────── ingest ──────────────┐
 git log -p ──▶│ hunks → tree-sitter spans          │
 git blame  ──▶│ live-line ownership per entity     │──▶  Neo4j
 GitHub GQL ──▶│ PRs, reviews, issues, people       │     (:CodeEntity)<-[:MODIFIED|OWNS_LINES]-(:Commit)
 design.rst ──▶│                                    │     (:Commit)-[:PART_OF]->(:PullRequest)-[:CLOSES]->(:Issue)
               └────────────────────────────────────┘     (:Decision)-[:AFFECTS]->(:CodeEntity)
               ┌────────────── extract ─────────────┐     (:Decision)-[:EXTRACTED_FROM|IMPLEMENTED_BY|MOTIVATED_BY]->(…)
 Gemini ──────▶│ decisions + verified quotes        │     (:Decision)-[:SUPERSEDES|REFINES]->(:Decision)
               │ inferred reasons for hotspots      │     (:Person)-[:AUTHORED|REVIEWED|COMMENTED]->(…)
               │ supersession judge                 │     vector indexes on Decision & CodeEntity (bge-small, 384d)
 bge-small ───▶│ embeddings (local, no quota)       │     full-text indexes on names & decision text
               └────────────────────────────────────┘
                                   │
   question ──▶ resolve entities (exact → full-text → vector)
            ──▶ GraphRAG: graph neighbours ∪ vector hits → expand evidence subgraph
            ──▶ confidence from graph facts → refuse or answer with [D1] citations
            ──▶ Next.js UI: answer · evidence chain · interactive graph · who to ask
```

### Confidence (computed, never asked of the LLM)

| Signal | Effect |
|---|---|
| Reason stated in source (quote verified) / reviewer-confirmed / maintainer-authored | +35–45 |
| Reason only inferred by AI, unreviewed | +10 |
| Decision's code still live in `git blame` at HEAD | +20 (rewritten: −10) |
| Linked issues, other reviewers, linked bug/incident | +5…+15 each |
| Superseded by a later decision | capped at 20 |

`high ≥ 70 · medium ≥ 45 · low ≥ 25 · otherwise: refuse.`

### Human in the loop (admin console)

* **Review queue**: reasons the AI inferred (from code + commit diff when nobody wrote one down, or from text whose
  quote couldn't be verified). Confirm, edit or reject them.
* **Write a decision**: maintainers record reasoning that lives only in their heads, link it to code, and optionally mark
  older decisions as replaced. It is embedded and searchable immediately.
* **Knowledge gaps**: coverage of busy code, undocumented hotspots, single-owner code (bus factor), silent commits, and
  questions users asked that nobody could answer.

## Running it

Prereqs: Docker, [uv](https://docs.astral.sh/uv/), Node 20+. Copy `.env.example` to `.env` and fill in (it is git-ignored):
`GITHUB_TOKEN` (read-only public), `GEMINI_API_KEY`.

```bash
docker compose --env-file .env up -d            # Neo4j 5 on :7474 / :7687
cd backend && uv sync
uv run python -m whygraph.cli all               # git → github → load → extract → infer → supersede → embed
uv run uvicorn whygraph.api:app --port 8000     # API
cd ../frontend && npm install && npm run dev    # UI on :3000
```

Every network/LLM call is cached under `data/cache/`, so the pipeline is resumable and re-runs are free. The LLM
client rotates across Gemini models on overload/quota errors (`GEMINI_MODELS` in `.env`).

Useful commands:

```bash
uv run python -m whygraph.cli status
uv run python -m whygraph.cli ask "Why does Flask run async views in a thread?"
uv run python -m whygraph.eval                  # retrieval / supersession / refusal metrics → data/eval.json
```

Switching to **Neo4j AuraDB Free**: set `NEO4J_URI=neo4j+s://<id>.databases.neo4j.io`, `NEO4J_USER`, `NEO4J_PASSWORD`
and run `cli load --wipe && cli extract && cli infer && cli supersede && cli embed` (LLM results come from the cache).

## Evaluation

Broad "why is X like this?" questions surface the target decision **82.5%** of the time; superseded decisions are
always flagged (18/18) and shown with their replacement 91% of the time; out-of-scope questions are refused 6/6.
Full method and caveats: [EVAL.md](EVAL.md).

## Disclosure

Built during the league timeline with AI assistance (Claude Code). Runtime AI: Google Gemini (extraction, supersession
judging, answer writing) and BAAI `bge-small-en-v1.5` (local embeddings). Open-source: Neo4j, tree-sitter, FastAPI,
Next.js, Cytoscape.js.
