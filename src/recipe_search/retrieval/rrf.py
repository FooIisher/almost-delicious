"""Deterministic, weighted reciprocal rank fusion of ordered ES hits."""

from __future__ import annotations

import math
from typing import Any


def recipe_id(hit: dict[str, Any]) -> str:
    """The ingestion pipeline sets ES _id = str(source.recipeid)."""
    value = hit.get("_source", {}).get("recipeid")
    if value is None:
        value = hit.get("_id")
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("Candidate has no valid recipe ID")
    return str(value).strip()


def unique_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first occurrence, then assign contiguous one-based ranks."""
    unique: dict[str, dict[str, Any]] = {}
    for hit in hits:
        unique.setdefault(recipe_id(hit), hit)
    return list(unique.values())


def reciprocal_rank_fusion(
    bm25_hits: list[dict[str, Any]],
    vector_hits: list[dict[str, Any]],
    *,
    k: int = 1,
    size: int = 20,
    bm25_boost: float = 1.0,
    vector_boost: float = 1.0,
) -> list[dict[str, Any]]:
    """Fuse by recipe ID. Raw ES scores never affect fusion or tie breaking.

    Missing branches contribute zero. Ties use best branch rank, then the
    canonical ID in lexical order. Inputs and source dictionaries are untouched.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("size must be a positive integer")
    boosts = {"bm25": bm25_boost, "vector": vector_boost}
    for boost in boosts.values():
        if (
            isinstance(boost, bool)
            or not isinstance(boost, (int, float))
            or not math.isfinite(boost)
            or boost <= 0
        ):
            raise ValueError("Boosts must be finite positive numbers")
    merged: dict[str, dict[str, Any]] = {}
    for branch, hits in (("bm25", bm25_hits), ("vector", vector_hits)):
        for rank, hit in enumerate(unique_hits(hits), start=1):
            identifier = recipe_id(hit)
            row = merged.setdefault(
                identifier,
                {
                    "recipe_id": identifier,
                    "hit": hit,  # Prefer BM25's hit, including lexical highlights.
                    "bm25_rank": None,
                    "vector_rank": None,
                    "bm25_score": None,
                    "vector_score": None,
                    "bm25_contribution": 0.0,
                    "vector_contribution": 0.0,
                    "rrf_score": 0.0,
                },
            )
            row[f"{branch}_rank"] = rank
            row[f"{branch}_score"] = hit.get("_score")
            row[f"{branch}_contribution"] = boosts[branch] / (k + rank)
            row["rrf_score"] += row[f"{branch}_contribution"]

    ordered = sorted(
        merged.values(),
        key=lambda row: (
            -row["rrf_score"],
            min(rank for rank in (row["bm25_rank"], row["vector_rank"]) if rank is not None),
            row["recipe_id"],
        ),
    )
    return [{**row, "rank": rank} for rank, row in enumerate(ordered[:size], start=1)]
