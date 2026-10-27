"""Confidence comes from facts in the graph, never from the LLM's self-assessment."""
from __future__ import annotations


def score(d: dict) -> dict:
    factors: list[dict] = []

    def add(label: str, delta: int, ok: bool | None):
        factors.append({"label": label, "delta": delta, "ok": ok})

    status = d.get("status")
    if status == "authored":
        add("Written by a maintainer in the admin console", 40, True)
    elif status == "confirmed":
        add("AI-inferred reason confirmed by a reviewer", 35, True)
    elif status == "explicit":
        add("Reason stated explicitly in the source", 35, True)
    else:
        add("Reason inferred by AI, not yet reviewed", 10, False)

    if status in ("explicit", "confirmed") and d.get("quote_verified"):
        add("Quote verified verbatim against the source", 10, True)

    live = d.get("live_lines")
    if live is None:
        add("Design-level decision (no specific lines to blame)", 5, None)
    elif live > 0:
        add(f"Its code is still live at HEAD ({live} line{'s' if live != 1 else ''} in git blame)", 20, True)
    else:
        add("Its code has since been rewritten", -10, False)

    n_issues = d.get("n_issues") or 0
    if n_issues:
        add(f"Corroborated by {n_issues} linked issue{'s' if n_issues > 1 else ''}", min(5 * n_issues, 15), True)
    if d.get("n_reviewers"):
        add(f"Reviewed by {d['n_reviewers']} other maintainer{'s' if d['n_reviewers'] > 1 else ''}", 5, True)
    if d.get("has_incident"):
        add("Linked to a bug or incident report", 10, True)

    total = sum(f["delta"] for f in factors)
    if d.get("superseded"):
        factors.append({"label": "Superseded by a later decision", "delta": min(0, 20 - total), "ok": False})
        total = min(total, 20)
    total = max(0, min(100, total))
    level = "high" if total >= 70 else "medium" if total >= 45 else "low" if total >= 25 else "insufficient"
    return {"score": total, "level": level, "factors": factors}
