#!/usr/bin/env python3
"""Recipe search API: BM25, vector and hybrid retrieval with ingredient filters."""

from __future__ import annotations

import json
import queue
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from elasticsearch import NotFoundError

from search_recipes import encode_query
from recipe_display_image import enrich_recipe_for_display
from semantic_search import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ES_URL,
    DEFAULT_INDEX,
    connect_elasticsearch,
    load_embedding_model,
)

Mode = Literal["bm25", "vector", "hybrid"]
CookTime = Literal["less_30", "30_60", "60_120", "120_180", "more_180"]
ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "web"
SOURCE_EXCLUDES = ["content_vector", "embedding_text", "searchable_text", "instructions_text"]


class SearchRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    mode: Mode = "hybrid"
    include_ingredients: list[str] = Field(default_factory=list)
    exclude_ingredients: list[str] = Field(default_factory=list)
    # Kept as the public field name for API compatibility. The selected range
    # applies to total recipe time, which is what the browser labels show.
    cook_time: CookTime | None = None
    max_total_time_minutes: Annotated[int | None, Field(ge=0)] = None
    max_calories: Annotated[float | None, Field(ge=0)] = None
    size: Annotated[int, Field(default=10, ge=1, le=50)] = 10

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Query cannot be empty")
        return value

    @field_validator("include_ingredients", "exclude_ingredients")
    @classmethod
    def clean_ingredients(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


@lru_cache(maxsize=1)
def get_client() -> Any:
    return connect_elasticsearch(DEFAULT_ES_URL)


@lru_cache(maxsize=1)
def get_model() -> Any:
    return load_embedding_model(DEFAULT_EMBEDDING_MODEL)


def ingredient_filters(include: list[str], exclude: list[str]) -> dict[str, Any] | None:
    """Case-insensitive substring matching for the keyword-mapped ingredients array."""
    if not include and not exclude:
        return None

    wildcard = lambda ingredient: {
        "wildcard": {"ingredients": {"value": f"*{ingredient.lower()}*", "case_insensitive": True}}
    }
    return {
        "bool": {
            "filter": [wildcard(ingredient) for ingredient in include],
            "must_not": [wildcard(ingredient) for ingredient in exclude],
        }
    }


def total_time_bucket_filter(value: CookTime | None) -> dict[str, Any] | None:
    """Map the browser's total-time buckets to Elasticsearch minute ranges."""
    ranges = {
        "less_30": {"lt": 30},
        "30_60": {"gte": 30, "lte": 60},
        "60_120": {"gte": 60, "lte": 120},
        "120_180": {"gt": 120, "lte": 180},
        "more_180": {"gt": 180},
    }
    return {"range": {"total_time_minutes": ranges[value]}} if value else None


def build_filters(request: SearchRequest) -> dict[str, Any] | None:
    ingredient = ingredient_filters(request.include_ingredients, request.exclude_ingredients)
    total_time_bucket = total_time_bucket_filter(request.cook_time)
    numeric_filters: list[dict[str, Any]] = []
    if request.max_total_time_minutes is not None:
        numeric_filters.extend([
            {"exists": {"field": "total_time_minutes"}},
            {"range": {"total_time_minutes": {"lte": request.max_total_time_minutes}}},
        ])
    if request.max_calories is not None:
        numeric_filters.extend([
            {"exists": {"field": "calories"}},
            {"range": {"calories": {"lte": request.max_calories}}},
        ])
    if not ingredient and not total_time_bucket and not numeric_filters:
        return None
    return {
        "bool": {
            "filter": (ingredient or {"bool": {}}).get("bool", {}).get("filter", []) + ([total_time_bucket] if total_time_bucket else []) + numeric_filters,
            "must_not": (ingredient or {"bool": {}}).get("bool", {}).get("must_not", []),
        }
    }


def bm25_query(query: str, filters: dict[str, Any] | None) -> dict[str, Any]:
    lexical_match: dict[str, Any] = {
        "multi_match": {
            "query": query,
            "fields": ["name^5", "keywords^3", "ingredients^2", "description^2", "searchable_text"],
            "type": "best_fields",
            # Prototype baseline: require literal analyzed terms.  Typo
            # tolerance can be introduced later as an explicit search mode.
            "fuzziness": 0,
            # Require every term for one- or two-word queries; for longer
            # natural-language queries require 75% of the terms instead.
            "minimum_should_match": "2<75%",
        }
    }
    # Keep broad multi-field recall, but reward a contiguous query phrase in
    # the title so exact recipe-title matches are ranked first.
    title_phrase_boost: dict[str, Any] = {
        "match_phrase": {"name": {"query": query, "boost": 12}}
    }
    bool_query: dict[str, Any] = {
        "must": [lexical_match],
        "should": [title_phrase_boost],
    }
    if filters:
        bool_query["filter"] = filters["bool"]["filter"]
        bool_query["must_not"] = filters["bool"]["must_not"]
    return {"bool": bool_query}


def search(
    request: SearchRequest,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, float], dict[str, Any]]:
    def emit(step: str, status: str, elapsed_ms: float | None = None) -> None:
        if on_progress:
            event: dict[str, Any] = {"type": "progress", "step": step, "status": status}
            if elapsed_ms is not None:
                event["elapsed_ms"] = round(elapsed_ms, 1)
            on_progress(event)

    filters = build_filters(request)
    embedding_ms = 0.0
    query_vector: list[float] | None = None

    if request.mode in {"vector", "hybrid"}:
        emit("embedding", "running")
        embedding_started = time.perf_counter()
        query_vector = encode_query(get_model(), request.query)
        embedding_ms = (time.perf_counter() - embedding_started) * 1000
        emit("embedding", "complete", embedding_ms)
    else:
        emit("embedding", "skipped")

    # Preserve ES' source payload for result-level debugging, but do not send
    # the large internal vector/text fields to the browser.
    body: dict[str, Any] = {
        "index": DEFAULT_INDEX,
        "size": request.size,
        "track_total_hits": True,
        "source": {"excludes": SOURCE_EXCLUDES},
    }
    if request.mode in {"bm25", "hybrid"}:
        body["query"] = bm25_query(request.query, filters)
        # Return concise lexical evidence for the result cards.  The browser
        # escapes every fragment and only renders the ES <em> markers as marks.
        body["highlight"] = {
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
            "fields": {
                "name": {"number_of_fragments": 0},
                "keywords": {"number_of_fragments": 0},
                "ingredients": {"number_of_fragments": 0},
                "description": {"fragment_size": 160, "number_of_fragments": 1},
            },
        }
    if request.mode in {"vector", "hybrid"}:
        knn: dict[str, Any] = {
            "field": "content_vector", "query_vector": query_vector,
            "k": request.size, "num_candidates": max(request.size * 5, 50),
        }
        # Apply the same filters to both BM25 and kNN branches.  In hybrid
        # search Elasticsearch merges those branches, so filtering only one
        # branch could otherwise reintroduce excluded ingredients.
        if filters:
            knn["filter"] = filters
        body["knn"] = knn

    emit("retrieving", "running")
    retrieval_started = time.perf_counter()
    response = get_client().search(**body)
    retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
    emit("retrieving", "complete", retrieval_ms)
    results = []
    for rank, hit in enumerate(response["hits"]["hits"], start=1):
        source = hit.get("_source", {})
        display_recipe = enrich_recipe_for_display(source)
        results.append(
            {
                "rank": rank,
                "score": round(hit["_score"], 4),
                # Elasticsearch maps cosine similarity (-1..1) to a positive
                # score for ranking: (cosine + 1) / 2.  Expose cosine only for
                # pure vector retrieval; hybrid's score combines two signals.
                **({"semantic_similarity": round(hit["_score"] * 2 - 1, 4)} if request.mode == "vector" else {}),
                "match_highlights": hit.get("highlight", {}),
                **display_recipe,
                "es_source": source,
            }
        )
    total = response["hits"].get("total", 0)
    if isinstance(total, dict):
        match_result_size = {"value": total.get("value", 0), "relation": total.get("relation", "eq")}
    else:  # Elasticsearch 6 compatibility
        match_result_size = {"value": total, "relation": "eq"}
    return results, {"query_embedding_ms": round(embedding_ms, 1), "es_retrieving_ms": round(retrieval_ms, 1)}, match_result_size


app = FastAPI(title="Recipe Search Prototype 1.0", version="1.0.0")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
@app.get("/api/health", include_in_schema=False)
def health() -> dict[str, str]:
    try:
        if not get_client().ping():
            raise RuntimeError("Elasticsearch ping returned false")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Elasticsearch is unavailable") from exc
    return {"status": "ok", "elasticsearch": "available"}


@app.post("/recipes/search")
@app.post("/api/search", include_in_schema=False)
def api_search(request: SearchRequest) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        results, timings, match_result_size = search(request)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Search failed while querying Elasticsearch.",
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
        ) from exc
    timings["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return {
        "query": request.query,
        "mode": request.mode,
        "result_count": len(results),
        "match_result_size": match_result_size,
        "timings": timings,
        "results": results,
    }


@app.get("/recipes/{recipe_id}")
def recipe_detail(recipe_id: str) -> dict[str, Any]:
    """Return the full persisted recipe record for the details view."""
    try:
        response = get_client().get(
            index=DEFAULT_INDEX,
            id=recipe_id,
            source_excludes=SOURCE_EXCLUDES,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Recipe {recipe_id!r} was not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Recipe detail lookup failed") from exc

    source = response.get("_source", {})
    return {
        **enrich_recipe_for_display(source),
        "source_identifier": f"elasticsearch:{DEFAULT_INDEX}",
    }


@app.post("/api/search/stream")
def api_search_stream(request: SearchRequest) -> StreamingResponse:
    """Send actual retrieval stage transitions to the prototype UI over SSE."""
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def worker() -> None:
        started = time.perf_counter()
        try:
            results, timings, match_result_size = search(request, events.put)
            timings["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
            events.put({
                "type": "result", "query": request.query, "mode": request.mode,
                "result_count": len(results), "match_result_size": match_result_size,
                "timings": timings, "results": results,
            })
        except Exception as exc:
            events.put({
                "type": "error", "message": "Search failed while querying Elasticsearch.",
                "exception_type": type(exc).__name__, "exception": str(exc),
            })
        finally:
            events.put(None)

    def stream() -> Any:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while (event := events.get()) is not None:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
