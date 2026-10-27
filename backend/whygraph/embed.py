"""Local embeddings (no API quota). bge-small: 384-dim, fast on CPU."""
from __future__ import annotations

from functools import lru_cache

from .config import EMBED_MODEL


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBED_MODEL)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return [v.tolist() for v in _model().embed(texts, batch_size=32)]


def embed_query(text: str) -> list[float]:
    # bge models retrieve better with this instruction prefix on the query side.
    return [float(x) for x in next(iter(_model().query_embed([text])))]
