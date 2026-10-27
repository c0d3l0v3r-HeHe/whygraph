"""HTTP API.  Run:  uv run uvicorn whygraph.api:app --reload --port 8000"""
from __future__ import annotations

import logging
import subprocess

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import admin, db
from .config import ADMIN_TOKEN, REPO_PATH, REPO_SLUG
from .query.ask import ask, decision_details

logging.basicConfig(level=logging.INFO)
for noisy in ("httpx", "neo4j", "google_genai"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

app = FastAPI(title="WhyGraph", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def require_admin(x_admin_token: str | None = Header(default=None)):
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "admin token required")


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class ReviewIn(BaseModel):
    action: str
    reviewer: str = "maintainer"
    title: str | None = None
    decision: str | None = None
    rationale: str | None = None


class AuthorIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    decision: str = Field(min_length=3)
    rationale: str = ""
    alternatives: list[str] = []
    kind: str = "design"
    author: str = "maintainer"
    entity_ids: list[str] = []
    entity_names: list[str] = []
    supersedes: list[str] = []


@app.get("/api/health")
def health():
    return {"ok": True, "neo4j": db.ping(), "repo": REPO_SLUG}


@app.get("/api/overview")
def overview():
    counts = {r["k"]: r["v"] for r in db.run(
        """CALL () { MATCH (n:CodeEntity {alive: true}) RETURN 'entities' AS k, count(n) AS v
           UNION ALL MATCH (n:Commit) RETURN 'commits' AS k, count(n) AS v
           UNION ALL MATCH (n:PullRequest) RETURN 'prs' AS k, count(n) AS v
           UNION ALL MATCH (n:Issue) RETURN 'issues' AS k, count(n) AS v
           UNION ALL MATCH (n:Person) RETURN 'people' AS k, count(n) AS v
           UNION ALL MATCH (n:Decision) WHERE n.status <> 'rejected' RETURN 'decisions' AS k, count(n) AS v
           UNION ALL MATCH (n:Decision {status: 'inferred'}) WHERE n.kind <> 'revert' RETURN 'pending' AS k, count(n) AS v
           UNION ALL MATCH ()-[r:SUPERSEDES]->() RETURN 'supersessions' AS k, count(r) AS v }
           RETURN k, v""")}
    span = db.run("MATCH (c:Commit) RETURN min(c.date) AS first, max(c.date) AS last")[0]
    return {"repo": REPO_SLUG, "counts": counts, "first_commit": span["first"], "last_commit": span["last"]}


@app.get("/api/examples")
def examples():
    """Suggested questions: busy entities with well-evidenced decisions, plus one superseded and one gap."""
    good = db.run(
        """MATCH (d:Decision)-[a:AFFECTS]->(e:CodeEntity)
           WHERE d.status IN ['explicit','confirmed'] AND a.mentioned AND e.alive AND e.kind <> 'module'
           WITH e, count(d) AS n, max(CASE WHEN d.superseded THEN 1 ELSE 0 END) AS has_sup
           RETURN e.qualname AS q, e.kind AS kind, n, has_sup ORDER BY has_sup DESC, n DESC, e.churn DESC LIMIT 6""")
    gap = db.run(
        """MATCH (e:CodeEntity) WHERE e.alive AND e.kind IN ['method','function'] AND e.churn >= 4
             AND NOT EXISTS { (:Decision)-[:AFFECTS]->(e) }
           RETURN e.qualname AS q ORDER BY e.churn DESC LIMIT 1""")
    if REPO_SLUG == "pallets/flask":
        # Hand-picked demo questions: each one shows a different capability.
        out = [
            "Why did Flask introduce FLASK_ENV, and is it still used?",           # supersession
            "Why are async views run in a thread instead of making Flask ASGI?",  # design doc + PR agree
            "Why does TRAP_BAD_REQUEST_ERRORS only trap key errors in debug?",    # superseded default
            "Why is MAX_COOKIE_SIZE 4093?",                                       # config key
            "Why does `jsonify` accept a list?",                                  # API shape + rejected option
            "Why was RequestContext merged into AppContext?",                     # recent refactor
        ]
    else:
        out = []
        for r in good:
            name = r["q"].replace("config:", "")
            out.append(f"Why is the {name} config default set the way it is?" if r["kind"] == "config"
                       else f"Why does `{name}` work the way it does?")
    if gap:
        out.append(f"Why is `{gap[0]['q']}` implemented like this?")         # honest "no recorded decision"
    return {"examples": out[:8]}


@app.post("/api/ask")
def ask_endpoint(body: AskIn):
    return ask(body.question)


@app.get("/api/decisions")
def decisions_list(status: str = "", q: str = "", superseded: bool = False, limit: int = 60):
    return db.run(
        """MATCH (d:Decision) WHERE d.status <> 'rejected'
             AND ($status = '' OR d.status = $status)
             AND (NOT $sup OR d.superseded)
             AND ($q = '' OR toLower(d.title + ' ' + d.decision + ' ' + coalesce(d.rationale, '')) CONTAINS toLower($q))
           OPTIONAL MATCH (d)-[a:AFFECTS]->(e:CodeEntity) WHERE a.mentioned
           WITH d, collect(e {.id, .qualname, .kind})[..3] AS ents
           OPTIONAL MATCH (n:Decision)-[:SUPERSEDES]->(d)
           RETURN d {.id, .title, .decision, .status, .date, .epoch, .superseded, .source_type, .source_ref,
                     .source_url, .kind} AS d, ents, collect(n.title)[..1] AS superseded_by
           ORDER BY coalesce(d.epoch, 0) DESC LIMIT $limit""",
        status=status, q=q, sup=superseded, limit=limit)


@app.get("/api/decisions/{decision_id:path}")
def decision(decision_id: str):
    res = decision_details([decision_id])
    if not res:
        raise HTTPException(404)
    return res[0]


@app.get("/api/entities/search")
def entity_search(q: str = "", limit: int = 12):
    if not q:
        return []
    return db.run(
        """MATCH (e:CodeEntity) WHERE e.alive AND e.kind <> 'module'
             AND (toLower(e.qualname) CONTAINS toLower($q) OR toLower(e.path) CONTAINS toLower($q))
           RETURN e {.id, .qualname, .kind, .path, .churn} AS e
           ORDER BY CASE WHEN toLower(e.name) = toLower($q) THEN 0 ELSE 1 END, e.churn DESC LIMIT $limit""",
        q=q, limit=limit)


@app.get("/api/entities/{entity_id:path}")
def entity(entity_id: str):
    rows = db.run("MATCH (e:CodeEntity {id: $id}) RETURN e {.*, embedding: null} AS e", id=entity_id)
    if not rows:
        raise HTTPException(404)
    e = rows[0]["e"]
    dec_ids = [r["id"] for r in db.run(
        """MATCH (d:Decision)-[:AFFECTS]->(e:CodeEntity {id: $id}) WHERE d.status <> 'rejected'
           RETURN d.id AS id""", id=entity_id)]
    decisions = sorted(decision_details(dec_ids), key=lambda d: d.get("epoch") or 0, reverse=True)
    owners = db.run(
        """MATCH (c:Commit)-[o:OWNS_LINES]->(:CodeEntity {id: $id}) MATCH (p:Person)-[:AUTHORED]->(c)
           RETURN coalesce(p.login, p.name) AS name, p.url AS url, p.last_active AS last_active, sum(o.lines) AS lines
           ORDER BY lines DESC LIMIT 6""", id=entity_id)
    history = db.run(
        """MATCH (c:Commit)-[m:MODIFIED]->(:CodeEntity {id: $id}) WHERE NOT c.formatting
           OPTIONAL MATCH (c)-[:PART_OF]->(p:PullRequest)
           OPTIONAL MATCH (a:Person)-[:AUTHORED]->(c)
           RETURN c.short AS short, c.subject AS subject, c.url AS url, c.date AS date, m.lines AS lines,
                  p.number AS pr, coalesce(a.login, a.name) AS author
           ORDER BY c.epoch DESC LIMIT 25""", id=entity_id)
    code = ""
    if e.get("alive"):
        real = REPO_PATH / ("src/" + e["path"]) if (REPO_PATH / ("src/" + e["path"])).exists() else REPO_PATH / e["path"]
        try:
            lines = real.read_text().splitlines()
            code = "\n".join(lines[e["start_line"] - 1 : min(e["end_line"], e["start_line"] + 80)])
        except OSError:
            pass
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_PATH, capture_output=True, text=True).stdout.strip()
    real_path = ("src/" + e["path"]) if (REPO_PATH / ("src/" + e["path"])).exists() else e["path"]
    e["github_url"] = f"https://github.com/{REPO_SLUG}/blob/{head}/{real_path}#L{e['start_line']}-L{e['end_line']}"
    return {"entity": e, "decisions": decisions, "owners": owners, "history": history, "code": code}


@app.get("/api/admin/review", dependencies=[Depends(require_admin)])
def review_queue():
    return admin.review_queue()


@app.post("/api/admin/decisions/{decision_id:path}/review", dependencies=[Depends(require_admin)])
def review(decision_id: str, body: ReviewIn):
    try:
        return admin.review(decision_id, body.action, body.reviewer, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/admin/decisions", dependencies=[Depends(require_admin)])
def author(body: AuthorIn):
    return admin.author_decision(body.model_dump())


@app.get("/api/admin/gaps", dependencies=[Depends(require_admin)])
def gaps():
    return admin.gaps()
