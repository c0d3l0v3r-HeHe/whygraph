"""Fetch merged PRs (with discussion + reviews) and issues via GitHub GraphQL.
Every page is cached on disk, so re-runs are free and resumable."""
from __future__ import annotations

import json
import logging
import time

import httpx

from .. import cache
from ..config import DATA_DIR, GITHUB_TOKEN, REPO_SLUG

log = logging.getLogger(__name__)
OUT = DATA_DIR / "github.json"

PR_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequests(first: 25, after:$cursor, states: MERGED, orderBy:{field:CREATED_AT, direction:ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body url createdAt mergedAt
        author { login }
        mergeCommit { oid }
        labels(first: 10) { nodes { name } }
        closingIssuesReferences(first: 10) { nodes { number } }
        commits(first: 100) { nodes { commit { oid authors(first: 3) { nodes { email name user { login } } } } } }
        comments(first: 40) { nodes { author { login } body createdAt } }
        reviews(first: 30) { nodes { author { login } body state submittedAt
                                     comments(first: 20) { nodes { body path } } } }
      }
    }
  }
  rateLimit { remaining resetAt }
}"""

ISSUE_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    issues(first: 50, after:$cursor, orderBy:{field:CREATED_AT, direction:ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body url createdAt closedAt state stateReason
        author { login }
        labels(first: 10) { nodes { name } }
        comments(first: 30) { nodes { author { login } body createdAt } }
      }
    }
  }
  rateLimit { remaining resetAt }
}"""


def _post(client: httpx.Client, query: str, variables: dict) -> dict:
    for attempt in range(6):
        try:
            r = client.post("https://api.github.com/graphql", json={"query": query, "variables": variables})
            if r.status_code == 200:
                data = r.json()
                if "errors" in data and not data.get("data"):
                    raise RuntimeError(str(data["errors"])[:300])
                return data["data"]
            log.warning("GitHub %s: %s", r.status_code, r.text[:200])
        except (httpx.HTTPError, RuntimeError) as e:
            log.warning("GitHub error: %s", e)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("GitHub GraphQL failed repeatedly")


def _paginate(client: httpx.Client, query: str, field: str) -> list[dict]:
    owner, name = REPO_SLUG.split("/")
    cursor = None
    nodes: list[dict] = []
    page = 0
    while True:
        key = json.dumps([field, owner, name, cursor])
        data = cache.get("github", key)
        if data is None:
            data = _post(client, query, {"owner": owner, "name": name, "cursor": cursor})
            cache.put("github", key, data)
            rl = data.get("rateLimit") or {}
            log.info("%s page %d (rate remaining %s)", field, page, rl.get("remaining"))
        conn = data["repository"][field]
        nodes.extend(conn["nodes"])
        page += 1
        if not conn["pageInfo"]["hasNextPage"]:
            # Don't cache the cursor of the final page forever: new items may appear later.
            break
        cursor = conn["pageInfo"]["endCursor"]
    return nodes


def run() -> dict:
    if not GITHUB_TOKEN:
        raise SystemExit("GITHUB_TOKEN is not set in .env")
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "User-Agent": "whygraph"}
    with httpx.Client(headers=headers, timeout=60) as client:
        prs = _paginate(client, PR_QUERY, "pullRequests")
        issues = _paginate(client, ISSUE_QUERY, "issues")
    result = {"prs": prs, "issues": issues}
    OUT.write_text(json.dumps(result))
    log.info("Fetched %d merged PRs, %d issues", len(prs), len(issues))
    return result


def load() -> dict:
    return json.loads(OUT.read_text())
