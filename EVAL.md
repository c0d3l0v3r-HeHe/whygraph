# Evaluation

`uv run python -m whygraph.eval` runs retrieval-only (no LLM calls) against the live graph built from
`pallets/flask` and writes `data/eval.json`.

Graph at evaluation time: 5,562 commits · 1,634 merged PRs · 2,768 issues · 517 live code entities ·
385 decisions (335 stated in source with a verified quote, 50 AI-inferred) · 27 supersession edges.

| Test | Result | What it measures |
|---|---|---|
| Broad questions (`Why does \`X\` work like this?`) | **82.5%** of target decisions appear in the 7 shown | Realistic: an entity usually has several valid decisions, so we check the target is among those surfaced |
| Specific questions (user describes the behaviour) | **97.5%** hit@1, **100%** hit@3 (40 cases) | Upper bound: questions reuse the decision's title, so this mostly checks entity + vector retrieval works end to end |
| Superseded decision shown with its replacement | **91%** (21/23) | When a decision was later overridden, does the answer include what replaced it? |
| Superseded decisions flagged as superseded | **18/18** returned | An overridden decision is never presented as current |
| Out-of-scope questions refused | **6/6** | Kubernetes, GraphQL, MongoDB, Kafka, a GPU scheduler, a payment gateway: none exist in Flask |

## Honest caveats

* The specific-question score is optimistic. A held-out set of human-written questions is the next step.
* Supersession recall is bounded by candidate generation: pairs are only judged when blame shows one decision's code
  replaced another's, when a revert exists, or when text references an earlier PR. Decisions that were overridden
  without touching the same code are missed.
* `git blame` runs with `-w -M10 -C10 -C10` so short lines (like a config default) are followed through file splits
  such as Flask's 2023 `app.py` → `sansio/app.py` move; formatting commits (Black, pyupgrade…) are skipped with
  `--ignore-rev`. Before this, config defaults moved in that split (e.g. `MAX_COOKIE_SIZE`) were credited to the
  refactor commit instead of the PR that introduced them.
* Extraction used Gemini free-tier models; when quota ran out the client fell back to lite models, which are slightly
  less precise. Every extracted quote is still checked verbatim against its source, and quotes that fail the check
  downgrade the decision to "AI-inferred" for human review.
