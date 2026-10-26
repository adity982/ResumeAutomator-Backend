"""Versioned local embeddings. Never substitute random/hash vectors for a model."""
from __future__ import annotations

from functools import lru_cache
import math

from ..config import settings

DIMENSIONS = 384


@lru_cache(maxsize=1)
def model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=settings.embedding_model, cache_dir=settings.model_cache_dir, threads=2)


def version() -> str:
    return f"fastembed:{settings.embedding_model}:384:v1" if settings.embedding_provider == "fastembed" else "none"


def embed(texts: list[str], *, query: bool = False) -> list[list[float] | None]:
    if not texts:
        return []
    if settings.embedding_provider == "lexical":
        return [None] * len(texts)
    encoder = model()
    vectors = encoder.query_embed(texts) if query else encoder.passage_embed(texts)
    result = []
    for vector in vectors:
        values = [float(value) for value in vector]
        if len(values) != DIMENSIONS or not all(math.isfinite(x) for x in values):
            raise ValueError("Embedding model must return 384 finite dimensions.")
        norm = math.sqrt(sum(x * x for x in values)) or 1
        result.append([x / norm for x in values])
    return result


def cosine(left, right) -> float:
    if left is None or right is None:
        return 0.0
    return sum(float(a) * float(b) for a, b in zip(left, right))
