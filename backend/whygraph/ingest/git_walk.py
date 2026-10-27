"""Walk the repository history.

Produces, for the whole history:
  * commit metadata (+ revert / issue references, size stats)
  * per-commit modified code entities (diff hunks mapped onto tree-sitter spans)
  * the current code entities at HEAD
  * git blame at HEAD aggregated per entity -> which commits own the live lines
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from ..config import DATA_DIR, PACKAGE_PREFIX, REPO_PATH
from .code_parse import Entity, locate, parse_entities

log = logging.getLogger(__name__)

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
REVERTS = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
REF = re.compile(r"(?<![\w/])#(\d{1,6})\b")
FORMATTING = re.compile(r"\b(black|reformat|pyupgrade|isort|pre-commit|format code|flake8|ruff|code style|apply style)\b", re.I)
# Big moves/splits rewrite lines without changing their meaning; blame should look through them.
STRUCTURAL = re.compile(r"\b(split|move[sd]?|rename[sd]?|reorgani[sz]e|restructure|sansio|src layout|relocate)\b", re.I)

OUT = DATA_DIR / "git.json"


def norm_path(p: str) -> str | None:
    if p.startswith("src/"):
        p = p[4:]
    if p.startswith(PACKAGE_PREFIX) and p.endswith(".py"):
        return p
    return None


def git(*args: str, cwd: Path = REPO_PATH) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          errors="replace").stdout


class BlobReader:
    """Persistent `git cat-file --batch` for fast file-at-revision reads."""

    def __init__(self, cwd: Path = REPO_PATH):
        self.p = subprocess.Popen(["git", "cat-file", "--batch"], cwd=cwd, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE)

    def read(self, rev: str, path: str) -> bytes | None:
        assert self.p.stdin and self.p.stdout
        self.p.stdin.write(f"{rev}:{path}\n".encode())
        self.p.stdin.flush()
        header = self.p.stdout.readline().decode().strip()
        if header.endswith("missing") or not header:
            return None
        size = int(header.split()[-1])
        data = self.p.stdout.read(size)
        self.p.stdout.read(1)  # trailing newline
        return data

    def close(self):
        if self.p.stdin:
            self.p.stdin.close()
        self.p.wait()


def read_commits() -> dict[str, dict]:
    raw = git("log", "--format=%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%B%x1f", "--numstat", "HEAD")
    commits: dict[str, dict] = {}
    for rec in raw.split("\x1e")[1:]:
        parts = rec.split("\x1f")
        if len(parts) < 7:
            continue
        sha, parents, an, ae, date, body, stat = parts[:7]
        adds = dels = py = 0
        files = []
        for line in stat.strip().splitlines():
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            a, d, f = cols
            a = int(a) if a.isdigit() else 0
            d = int(d) if d.isdigit() else 0
            adds += a
            dels += d
            files.append(f)
            if f.endswith(".py"):
                py += a + d
        body = body.strip()
        subject = body.split("\n", 1)[0]
        commits[sha] = {
            "sha": sha,
            "parents": parents.split(),
            "author_name": an,
            "author_email": ae.lower(),
            "date": date,
            "message": body[:4000],
            "subject": subject[:300],
            "is_merge": len(parents.split()) > 1,
            "reverts": REVERTS.findall(body),
            "is_revert": subject.lower().startswith("revert") or bool(REVERTS.search(body)),
            "refs": sorted({int(n) for n in REF.findall(body)}),
            "files": files[:200],
            "additions": adds,
            "deletions": dels,
            "py_lines": py,
            "entity_changes": {},
        }
    return commits


def map_hunks(commits: dict[str, dict], blobs: BlobReader, entities_seen: dict[str, dict]) -> None:
    """Stream `git log -p -U0` and attribute changed lines to code entities."""
    proc = subprocess.Popen(
        ["git", "log", "--no-merges", "-M", "--format=%x1e%H", "-p", "-U0", "--no-color", "--no-ext-diff",
         "HEAD", "--", "*.py"],
        cwd=REPO_PATH, stdout=subprocess.PIPE, text=True, errors="replace",
    )
    assert proc.stdout
    sha = None
    old_path = new_path = None
    new_lines: list[int] = []
    old_lines: list[int] = []

    def flush():
        if not sha or not (new_lines or old_lines):
            return
        c = commits.get(sha)
        if c is None:
            return
        changes: Counter = Counter()
        np = norm_path(new_path) if new_path else None
        op = norm_path(old_path) if old_path else None
        if np and new_path:
            src = blobs.read(sha, new_path)
            if src is not None:
                ents = parse_entities(np, src)
                for e in ents:
                    entities_seen.setdefault(e.id, e.to_dict())
                for ln in new_lines:
                    e = locate(ents, ln)
                    if e:
                        changes[e.id] += 1
        elif op and old_path and c["parents"]:
            # file deleted: attribute removed lines against the parent version
            src = blobs.read(c["parents"][0], old_path)
            if src is not None:
                ents = parse_entities(op, src)
                for e in ents:
                    entities_seen.setdefault(e.id, e.to_dict())
                for ln in old_lines:
                    e = locate(ents, ln)
                    if e:
                        changes[e.id] += 1
        for k, v in changes.items():
            c["entity_changes"][k] = c["entity_changes"].get(k, 0) + v

    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith("\x1e"):
            flush()
            sha = line[1:].strip()
            old_path = new_path = None
            new_lines, old_lines = [], []
        elif line.startswith("diff --git "):
            flush()
            old_path = new_path = None
            new_lines, old_lines = [], []
        elif line.startswith("--- "):
            old_path = None if line.endswith("/dev/null") else line[6:]
        elif line.startswith("+++ "):
            new_path = None if line.endswith("/dev/null") else line[6:]
        elif line.startswith("@@"):
            m = HUNK.match(line)
            if not m:
                continue
            o_start, o_len = int(m.group(1)), int(m.group(2) or 1)
            n_start, n_len = int(m.group(3)), int(m.group(4) or 1)
            if n_len > 0:
                new_lines.extend(range(n_start, n_start + n_len))
            else:
                new_lines.append(max(n_start, 1))  # pure deletion: anchor at position
            if o_len > 0:
                old_lines.extend(range(o_start, o_start + o_len))
    flush()
    proc.wait()


def head_entities(blobs: BlobReader) -> tuple[list[Entity], dict[str, str]]:
    files = [f for f in git("ls-files").splitlines() if norm_path(f)]
    ents: list[Entity] = []
    path_map = {}
    for f in files:
        src = blobs.read("HEAD", f)
        if src is None:
            continue
        np = norm_path(f)
        assert np
        path_map[np] = f
        ents.extend(parse_entities(np, src))
    return ents, path_map


def formatting_commits(commits: dict[str, dict]) -> list[str]:
    return [c["sha"] for c in commits.values()
            if not c["is_merge"] and ((c["py_lines"] > 150 and FORMATTING.search(c["subject"]))
                                      or (c["py_lines"] > 800 and STRUCTURAL.search(c["subject"])))]


def blame_head(ents: list[Entity], path_map: dict[str, str], ignore: list[str]) -> dict[str, dict[str, int]]:
    by_path: dict[str, list[Entity]] = defaultdict(list)
    for e in ents:
        by_path[e.path].append(e)
    ignore_args = [a for sha in ignore for a in ("--ignore-rev", sha)]
    owners: dict[str, Counter] = defaultdict(Counter)
    for np, real in path_map.items():
        # -M10/-C10 -C10: follow short lines through moves and file splits (e.g. app.py -> sansio/app.py)
        out = git("blame", "-w", "-M10", "-C10", "-C10", "--line-porcelain", *ignore_args, "HEAD", "--", real)
        line_no = 0
        for line in out.splitlines():
            if re.match(r"^[0-9a-f]{40} ", line):
                parts = line.split()
                sha, line_no = parts[0], int(parts[2])
                e = locate(by_path[np], line_no)
                if e:
                    owners[e.id][sha] += 1
    return {k: dict(v) for k, v in owners.items()}


def run() -> dict:
    log.info("Reading commit metadata…")
    commits = read_commits()
    log.info("%d commits", len(commits))
    blobs = BlobReader()
    seen: dict[str, dict] = {}
    log.info("Mapping diff hunks to code entities…")
    map_hunks(commits, blobs, seen)
    log.info("Parsing HEAD entities…")
    ents, path_map = head_entities(blobs)
    blobs.close()
    ignore = formatting_commits(commits)
    log.info("Blaming HEAD (ignoring %d formatting commits)…", len(ignore))
    blame = blame_head(ents, path_map, ignore)

    alive = {e.id for e in ents}
    all_entities = {e.id: {**e.to_dict(), "alive": True} for e in ents}
    for eid, d in seen.items():
        if eid not in alive:
            all_entities[eid] = {**d, "alive": False}

    result = {
        "head": git("rev-parse", "HEAD").strip(),
        "commits": list(commits.values()),
        "entities": list(all_entities.values()),
        "blame": blame,
        "formatting_commits": ignore,
    }
    OUT.write_text(json.dumps(result))
    log.info("Wrote %s (%d entities, %d alive)", OUT, len(all_entities), len(alive))
    return result


def load() -> dict:
    return json.loads(OUT.read_text())
