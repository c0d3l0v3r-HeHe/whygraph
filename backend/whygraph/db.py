"""Neo4j access + schema (constraints, full-text and vector indexes)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable

from neo4j import GraphDatabase

from .config import EMBED_DIM, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

_driver = None


def driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
                                       notifications_min_severity="OFF")
    return _driver


@contextmanager
def session():
    with driver().session() as s:
        yield s


def run(query: str, **params) -> list[dict[str, Any]]:
    with session() as s:
        return [r.data() for r in s.run(query, **params)]


def run_batched(query: str, rows: list[dict], batch: int = 500, **params) -> None:
    """Run an UNWIND $rows query in chunks."""
    with session() as s:
        for i in range(0, len(rows), batch):
            s.run(query, rows=rows[i : i + batch], **params).consume()


SCHEMA = [
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:CodeEntity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (n:File) REQUIRE n.path IS UNIQUE",
    "CREATE CONSTRAINT commit_sha IF NOT EXISTS FOR (n:Commit) REQUIRE n.sha IS UNIQUE",
    "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT pr_number IF NOT EXISTS FOR (n:PullRequest) REQUIRE n.number IS UNIQUE",
    "CREATE CONSTRAINT issue_number IF NOT EXISTS FOR (n:Issue) REQUIRE n.number IS UNIQUE",
    "CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (n:DesignDoc) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT decision_id IF NOT EXISTS FOR (n:Decision) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX decision_status IF NOT EXISTS FOR (n:Decision) ON (n.status)",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (n:CodeEntity) ON (n.name)",
    "CREATE FULLTEXT INDEX entity_text IF NOT EXISTS FOR (n:CodeEntity) ON EACH [n.name, n.qualname, n.doc]",
    "CREATE FULLTEXT INDEX decision_text IF NOT EXISTS FOR (n:Decision) ON EACH [n.title, n.decision, n.rationale]",
    "CREATE FULLTEXT INDEX source_text IF NOT EXISTS FOR (n:PullRequest|Issue|Commit) ON EACH [n.title, n.body, n.subject, n.message]",
    f"""CREATE VECTOR INDEX decision_embedding IF NOT EXISTS FOR (n:Decision) ON (n.embedding)
        OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBED_DIM}, `vector.similarity_function`: 'cosine'}}}}""",
    f"""CREATE VECTOR INDEX entity_embedding IF NOT EXISTS FOR (n:CodeEntity) ON (n.embedding)
        OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBED_DIM}, `vector.similarity_function`: 'cosine'}}}}""",
]


def init_schema() -> None:
    for q in SCHEMA:
        run(q)


def wipe() -> None:
    with session() as s:
        s.run("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS").consume()


def ping() -> bool:
    try:
        run("RETURN 1")
        return True
    except Exception:
        return False


def chunks(it: Iterable, n: int):
    buf = []
    for x in it:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf
