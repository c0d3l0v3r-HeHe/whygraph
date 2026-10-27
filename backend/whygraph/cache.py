"""Tiny disk cache so every network/LLM result is paid for once."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .config import CACHE_DIR


def _path(namespace: str, key: str) -> Path:
    h = hashlib.sha256(key.encode()).hexdigest()[:24]
    d = CACHE_DIR / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


def get(namespace: str, key: str) -> Any | None:
    p = _path(namespace, key)
    if p.exists():
        return json.loads(p.read_text())
    return None


def put(namespace: str, key: str, value: Any) -> None:
    p = _path(namespace, key)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value))
    tmp.replace(p)


def cached(namespace: str, key: str, fn: Callable[[], Any]) -> Any:
    hit = get(namespace, key)
    if hit is not None:
        return hit
    value = fn()
    if value is not None:
        put(namespace, key, value)
    return value
