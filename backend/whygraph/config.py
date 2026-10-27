"""Central settings, loaded from the repo-root .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("WHYGRAPH_DATA", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
REPOS_DIR = DATA_DIR / "repos"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Tried in order; on overload/quota errors the client falls through to the next one.
GEMINI_MODELS = [
    m.strip()
    for m in os.getenv(
        "GEMINI_MODELS",
        "gemini-3.5-flash,gemini-flash-lite-latest,gemini-3.5-flash-lite,gemini-flash-latest",
    ).split(",")
    if m.strip()
]
# Interactive answers: fast models first, bounded wait.
ANSWER_MODELS = [m.strip() for m in os.getenv(
    "ANSWER_MODELS", "gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-3.5-flash").split(",") if m.strip()]
ANSWER_DEADLINE = float(os.getenv("ANSWER_DEADLINE", "25"))
# Minimum seconds between LLM calls (free-tier friendly).
LLM_MIN_INTERVAL = float(os.getenv("LLM_MIN_INTERVAL", "4"))

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# The repository we analyse.
REPO_SLUG = os.getenv("WHYGRAPH_REPO", "pallets/flask")
REPO_NAME = REPO_SLUG.split("/")[-1]
REPO_PATH = REPOS_DIR / REPO_NAME
# Package directory whose code entities we index (paths are normalised to drop a leading "src/").
PACKAGE_PREFIX = os.getenv("WHYGRAPH_PACKAGE", "flask/")

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM = 384

for d in (DATA_DIR, CACHE_DIR, REPOS_DIR):
    d.mkdir(parents=True, exist_ok=True)
