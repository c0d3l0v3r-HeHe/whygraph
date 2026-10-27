"""Load the structural graph (code, commits, people, PRs, issues) into Neo4j."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from . import db
from .config import REPO_SLUG
from .ingest import git_walk, github_fetch

log = logging.getLogger(__name__)

REF = re.compile(r"(?<![\w/])#(\d{1,6})\b")
SQUASH_REF = re.compile(r"\(#(\d+)\)\s*$")
MERGE_PR = re.compile(r"^Merge pull request #(\d+)")
INCIDENT_LABELS = {"bug", "regression", "security", "crash"}
INCIDENT_TITLE = re.compile(r"\b(regression|crash|security|vulnerab|broke|broken|breaks|exception|traceback|error)\b", re.I)
TRIVIAL = re.compile(r"\b(typo|bump|release version|version \d|changelog|changes\.rst|pre-commit autoupdate|"
                     r"update requirements|merge branch|docs?:|fix (a )?link|whitespace|spelling)\b", re.I)
GH = f"https://github.com/{REPO_SLUG}"


def epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _discussion(pr: dict) -> str:
    parts = []
    for c in (pr.get("comments") or {}).get("nodes", []):
        parts.append(f"[comment by {((c.get('author') or {}).get('login')) or 'ghost'}] {c.get('body') or ''}")
    for r in (pr.get("reviews") or {}).get("nodes", []):
        who = (r.get("author") or {}).get("login") or "ghost"
        if r.get("body"):
            parts.append(f"[review {r.get('state')} by {who}] {r['body']}")
        for rc in (r.get("comments") or {}).get("nodes", []):
            parts.append(f"[review comment by {who} on {rc.get('path')}] {rc.get('body') or ''}")
    return "\n\n".join(parts)[:12000]


def _issue_discussion(issue: dict) -> str:
    parts = [f"[comment by {((c.get('author') or {}).get('login')) or 'ghost'}] {c.get('body') or ''}"
             for c in (issue.get("comments") or {}).get("nodes", [])]
    return "\n\n".join(parts)[:10000]


def run(wipe: bool = False) -> None:
    if wipe:
        log.info("Wiping graph…")
        db.wipe()
    db.init_schema()
    g = git_walk.load()
    gh = github_fetch.load()

    # ---------- people: resolve git emails -> GitHub logins via PR commit data ----------
    email_login: dict[str, str] = {}
    for pr in gh["prs"]:
        for cn in (pr.get("commits") or {}).get("nodes", []):
            for a in (cn["commit"].get("authors") or {}).get("nodes", []):
                login = (a.get("user") or {}).get("login")
                if login and a.get("email"):
                    email_login[a["email"].lower()] = login

    def person_id(email: str | None = None, login: str | None = None) -> str:
        if login:
            return f"gh:{login.lower()}"
        if email and email in email_login:
            return f"gh:{email_login[email].lower()}"
        return f"email:{(email or 'unknown').lower()}"

    # ---------- code entities + files ----------
    ents = g["entities"]
    files = sorted({e["path"] for e in ents})
    db.run_batched("UNWIND $rows AS r MERGE (f:File {path: r.p})", [{"p": p} for p in files])
    db.run_batched(
        """UNWIND $rows AS e
           MERGE (n:CodeEntity {id: e.id})
           SET n.path = e.path, n.name = e.name, n.qualname = e.qualname, n.kind = e.kind,
               n.start_line = e.start, n.end_line = e.end, n.doc = e.doc, n.signature = e.signature,
               n.alive = e.alive
           WITH n, e MATCH (f:File {path: e.path}) MERGE (f)-[:CONTAINS]->(n)""",
        ents,
    )
    db.run_batched(
        """UNWIND $rows AS e
           MATCH (c:CodeEntity {id: e.id}), (p:CodeEntity {id: e.parent})
           MERGE (p)-[:CONTAINS]->(c)""",
        [e for e in ents if e.get("parent")],
    )
    log.info("Loaded %d entities", len(ents))

    # ---------- commits ----------
    pr_numbers = {pr["number"] for pr in gh["prs"]}
    issue_numbers = {i["number"] for i in gh["issues"]}
    rows = []
    for c in g["commits"]:
        m = SQUASH_REF.search(c["subject"]) or MERGE_PR.match(c["subject"])
        rows.append({
            "sha": c["sha"], "short": c["sha"][:8], "subject": c["subject"], "message": c["message"],
            "date": c["date"], "epoch": epoch(c["date"]), "additions": c["additions"], "deletions": c["deletions"],
            "py_lines": c["py_lines"], "is_merge": c["is_merge"], "is_revert": c["is_revert"],
            "trivial": bool(TRIVIAL.search(c["subject"])) or (c["py_lines"] == 0),
            "formatting": c["sha"] in set(g["formatting_commits"]),
            "url": f"{GH}/commit/{c['sha']}",
            "person": person_id(c["author_email"]), "author_name": c["author_name"],
            "pr": int(m.group(1)) if m and int(m.group(1)) in pr_numbers else None,
            "refs": [n for n in c["refs"] if n in issue_numbers],
        })
    db.run_batched(
        """UNWIND $rows AS c
           MERGE (n:Commit {sha: c.sha})
           SET n.short = c.short, n.subject = c.subject, n.message = c.message, n.date = c.date,
               n.epoch = c.epoch, n.additions = c.additions, n.deletions = c.deletions, n.py_lines = c.py_lines,
               n.is_merge = c.is_merge, n.is_revert = c.is_revert, n.trivial = c.trivial,
               n.formatting = c.formatting, n.url = c.url
           MERGE (p:Person {id: c.person})
           ON CREATE SET p.name = c.author_name
           MERGE (p)-[:AUTHORED]->(n)""",
        rows,
    )
    log.info("Loaded %d commits", len(rows))

    # entity modifications + blame ownership
    mods = [{"sha": c["sha"], "eid": eid, "lines": n} for c in g["commits"] for eid, n in c["entity_changes"].items()]
    db.run_batched(
        """UNWIND $rows AS r MATCH (c:Commit {sha: r.sha}), (e:CodeEntity {id: r.eid})
           MERGE (c)-[m:MODIFIED]->(e) SET m.lines = r.lines""", mods, batch=2000)
    db.run("MATCH ()-[o:OWNS_LINES]->() DELETE o")
    owns = [{"sha": sha, "eid": eid, "lines": n} for eid, d in g["blame"].items() for sha, n in d.items()]
    db.run_batched(
        """UNWIND $rows AS r MATCH (c:Commit {sha: r.sha}), (e:CodeEntity {id: r.eid})
           MERGE (c)-[o:OWNS_LINES]->(e) SET o.lines = r.lines""", owns, batch=2000)
    reverts = [{"sha": c["sha"], "target": t} for c in g["commits"] for t in c["reverts"]]
    db.run_batched(
        """UNWIND $rows AS r MATCH (c:Commit {sha: r.sha}), (t:Commit) WHERE t.sha STARTS WITH r.target
           MERGE (c)-[:REVERTS]->(t)""", reverts)
    log.info("Loaded %d MODIFIED, %d OWNS_LINES, %d REVERTS", len(mods), len(owns), len(reverts))

    # ---------- issues ----------
    irows = []
    for i in gh["issues"]:
        labels = [l["name"] for l in (i.get("labels") or {}).get("nodes", [])]
        irows.append({
            "number": i["number"], "title": i["title"], "body": (i.get("body") or "")[:6000],
            "discussion": _issue_discussion(i), "url": i["url"], "created_at": i["createdAt"],
            "epoch": epoch(i["createdAt"]), "closed_at": i.get("closedAt"), "state": i.get("state"),
            "labels": labels,
            "is_incident": bool(INCIDENT_LABELS & {l.lower() for l in labels}) or bool(INCIDENT_TITLE.search(i["title"])),
            "person": person_id(login=(i.get("author") or {}).get("login") or "ghost"),
            "login": (i.get("author") or {}).get("login") or "ghost",
            "commenters": sorted({(c.get("author") or {}).get("login") for c in (i.get("comments") or {}).get("nodes", [])
                                  if (c.get("author") or {}).get("login")}),
        })
    db.run_batched(
        """UNWIND $rows AS i
           MERGE (n:Issue {number: i.number})
           SET n.title = i.title, n.body = i.body, n.discussion = i.discussion, n.url = i.url,
               n.created_at = i.created_at, n.epoch = i.epoch, n.closed_at = i.closed_at, n.state = i.state,
               n.labels = i.labels, n.is_incident = i.is_incident
           MERGE (p:Person {id: i.person}) ON CREATE SET p.login = i.login, p.name = i.login
           MERGE (p)-[:AUTHORED]->(n)
           WITH n, i UNWIND i.commenters AS who
           MERGE (q:Person {id: 'gh:' + toLower(who)}) ON CREATE SET q.login = who, q.name = who
           MERGE (q)-[:COMMENTED]->(n)""",
        irows, batch=200,
    )
    log.info("Loaded %d issues", len(irows))

    # ---------- pull requests ----------
    prows = []
    for pr in gh["prs"]:
        body = pr.get("body") or ""
        refs = {int(n) for n in REF.findall(body + " " + pr["title"])}
        reviewers = sorted({(r.get("author") or {}).get("login") for r in (pr.get("reviews") or {}).get("nodes", [])
                            if (r.get("author") or {}).get("login")})
        commenters = sorted({(c.get("author") or {}).get("login") for c in (pr.get("comments") or {}).get("nodes", [])
                             if (c.get("author") or {}).get("login")})
        login = (pr.get("author") or {}).get("login") or "ghost"
        commit_oids = [cn["commit"]["oid"] for cn in (pr.get("commits") or {}).get("nodes", [])]
        if pr.get("mergeCommit"):
            commit_oids.append(pr["mergeCommit"]["oid"])
        prows.append({
            "number": pr["number"], "title": pr["title"], "body": body[:8000], "discussion": _discussion(pr),
            "url": pr["url"], "created_at": pr["createdAt"], "merged_at": pr.get("mergedAt"),
            "epoch": epoch(pr.get("mergedAt") or pr["createdAt"]),
            "labels": [l["name"] for l in (pr.get("labels") or {}).get("nodes", [])],
            "login": login, "person": person_id(login=login),
            "reviewers": [r for r in reviewers if r != login], "commenters": [c for c in commenters if c != login],
            "closes": [n["number"] for n in (pr.get("closingIssuesReferences") or {}).get("nodes", [])],
            "refs_issues": sorted(n for n in refs if n in issue_numbers),
            "refs_prs": sorted(n for n in refs if n in pr_numbers and n != pr["number"]),
            "commits": commit_oids,
        })
    db.run_batched(
        """UNWIND $rows AS r
           MERGE (n:PullRequest {number: r.number})
           SET n.title = r.title, n.body = r.body, n.discussion = r.discussion, n.url = r.url,
               n.created_at = r.created_at, n.merged_at = r.merged_at, n.epoch = r.epoch, n.labels = r.labels
           MERGE (p:Person {id: r.person}) ON CREATE SET p.login = r.login, p.name = r.login
           SET p.login = r.login
           MERGE (p)-[:AUTHORED]->(n)
           WITH n, r
           CALL (n, r) { UNWIND r.reviewers AS who
                  MERGE (q:Person {id: 'gh:' + toLower(who)}) ON CREATE SET q.login = who, q.name = who
                  MERGE (q)-[:REVIEWED]->(n) }
           CALL (n, r) { UNWIND r.commenters AS who
                  MERGE (q:Person {id: 'gh:' + toLower(who)}) ON CREATE SET q.login = who, q.name = who
                  MERGE (q)-[:COMMENTED]->(n) }
           CALL (n, r) { UNWIND r.closes AS num MATCH (i:Issue {number: num}) MERGE (n)-[:CLOSES]->(i) }
           CALL (n, r) { UNWIND r.refs_issues AS num MATCH (i:Issue {number: num}) MERGE (n)-[:REFERENCES]->(i) }
           CALL (n, r) { UNWIND r.refs_prs AS num MATCH (o:PullRequest {number: num}) MERGE (n)-[:REFERENCES]->(o) }
           CALL (n, r) { UNWIND r.commits AS oid MATCH (c:Commit {sha: oid}) MERGE (c)-[:PART_OF]->(n) }""",
        prows, batch=100,
    )
    # squash/merge commits whose subject names the PR
    db.run_batched(
        """UNWIND $rows AS c MATCH (n:Commit {sha: c.sha}), (p:PullRequest {number: c.pr})
           MERGE (n)-[:PART_OF]->(p)""", [r for r in rows if r["pr"]])
    db.run_batched(
        """UNWIND $rows AS c UNWIND c.refs AS num MATCH (n:Commit {sha: c.sha}), (i:Issue {number: num})
           MERGE (n)-[:REFERENCES]->(i)""", [r for r in rows if r["refs"]])
    # Merge commits carry no diff of their own: let the PR inherit MODIFIED via its member commits.
    log.info("Loaded %d PRs", len(prows))

    # ---------- derived stats ----------
    db.run("""MATCH (e:CodeEntity)
              OPTIONAL MATCH (c:Commit)-[:MODIFIED]->(e) WHERE NOT c.formatting
              WITH e, count(DISTINCT c) AS churn, max(c.epoch) AS last
              OPTIONAL MATCH (p:Person)-[:AUTHORED]->(:Commit)-[:MODIFIED]->(e)
              WITH e, churn, last, count(DISTINCT p) AS authors
              SET e.churn = churn, e.last_modified = last, e.author_count = authors""")
    db.run("""MATCH (p:Person) OPTIONAL MATCH (p)-[:AUTHORED|REVIEWED|COMMENTED]->(x)
              WITH p, max(x.epoch) AS last, count(x) AS n
              SET p.last_active = last, p.activity = n""")
    db.run("MATCH (p:Person) WHERE p.login IS NOT NULL SET p.url = 'https://github.com/' + p.login")
    log.info("Structural graph loaded.")
