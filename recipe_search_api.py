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
from pydantic import BaseModel, Field, field_validator, model_validator
from elasticsearch import NotFoundError

from search_recipes import encode_query
from recipe_display_image import enrich_recipe_for_display
from preference_ranking import rerank, RULES
from rrf import recipe_id, unique_hits, reciprocal_rank_fusion
from retrieval_execution import execute_branches
from intent_service import router as intent_router
import gpt_intent_service  # Register the direct OpenAI preview route.
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
    labels: list[str] = Field(default_factory=list)
    preference_weight_available: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_weight_prefer: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_weight_avoid: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_weight_cuisine: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_weight_meal_type: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 3.0
    preference_weight_dish_type: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 2.0
    preference_healthy: list[str] = Field(default_factory=list)
    preference_weight_healthy: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_quick: list[str] = Field(default_factory=list)
    preference_weight_quick: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_easy: list[str] = Field(default_factory=list)
    preference_weight_easy: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_lambda: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.30
    rating_boost: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.10
    preference_available: list[str] = Field(default_factory=list)
    preference_prefer: list[str] = Field(default_factory=list)
    preference_avoid: list[str] = Field(default_factory=list)
    preference_cuisine: list[str] = Field(default_factory=list)
    preference_meal_type: list[str] = Field(default_factory=list)
    preference_dish_type: list[str] = Field(default_factory=list)

    # Kept as the public field name for API compatibility. The selected range
    # applies to total recipe time, which is what the browser labels show.
    cook_time: CookTime | None = None
    max_total_time_minutes: Annotated[int | None, Field(ge=0)] = None
    max_calories: Annotated[float | None, Field(ge=0)] = None
    size: Annotated[int, Field(default=20, ge=1, le=50)] = 20
    rrf_k: Annotated[int, Field(strict=True, ge=1, le=10000)] = 10
    bm25_candidates: Annotated[int, Field(strict=True, ge=1, le=2000)] = 50
    vector_candidates: Annotated[int, Field(strict=True, ge=1, le=2000)] = 50
    vector_num_candidates: Annotated[int | None, Field(strict=True, ge=1, le=10000)] = None
    bm25_boost: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 1.0
    vector_boost: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 2.0
    execution: Literal["parallel", "serial"] = "parallel"
    branch_timeout_seconds: Annotated[float, Field(gt=0, le=120, allow_inf_nan=False)] = 30.0

    @model_validator(mode="after")
    def validate_candidates(self) -> "SearchRequest":
        if self.mode == "hybrid" and min(self.bm25_candidates, self.vector_candidates) < self.size:
            raise ValueError("Each hybrid candidate count must be at least size")
        if self.vector_num_candidates is None:
            self.vector_num_candidates = max(250, self.vector_candidates) if self.mode == "hybrid" else 50
        vector_count = self.vector_candidates if self.mode == "hybrid" else self.size
        if self.mode != "bm25" and self.vector_num_candidates < vector_count:
            raise ValueError("vector_num_candidates must be at least the vector result count")
        return self

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

    @field_validator("preference_healthy", "preference_quick", "preference_easy", "labels", "preference_available", "preference_prefer", "preference_avoid", "preference_cuisine", "preference_meal_type", "preference_dish_type")
    @classmethod
    def clean_labels(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))


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
    if request.labels:
        numeric_filters.append({"bool": {
            "should": [{"term": {field: {"value": label, "case_insensitive": True}}}
                       for label in request.labels for field in ("recipecategory", "keywords")],
            "minimum_should_match": 1,
        }})
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


def retrieve_candidates(
    request: SearchRequest, filters: dict[str, Any] | None, branch: str,
) -> dict[str, Any]:
    """One independent ES search, with identical hard constraints in both paths."""
    count = (request.bm25_candidates if branch == "bm25" else request.vector_candidates) \
        if request.mode == "hybrid" else request.size
    body: dict[str, Any] = {
        "index": DEFAULT_INDEX, "size": count,
        "track_total_hits": branch == "bm25",
        "source": {"excludes": SOURCE_EXCLUDES},
    }
    timings: dict[str, float] = {}
    if branch == "bm25":
        body["query"] = bm25_query(request.query, filters)
        body["highlight"] = {
            "pre_tags": ["<em>"], "post_tags": ["</em>"],
            "fields": {
                "name": {"number_of_fragments": 0},
                "keywords": {"number_of_fragments": 0},
                "ingredients": {"number_of_fragments": 0},
                "description": {"fragment_size": 160, "number_of_fragments": 1},
            },
        }
    else:
        started = time.perf_counter()
        vector = encode_query(get_model(), request.query)
        timings["query_embedding_ms"] = (time.perf_counter() - started) * 1000
        body["knn"] = {
            "field": "content_vector", "query_vector": vector,
            "k": count, "num_candidates": request.vector_num_candidates,
        }
        if filters:
            body["knn"]["filter"] = filters

    started = time.perf_counter()
    response = get_client().options(
        request_timeout=request.branch_timeout_seconds, max_retries=0,
    ).search(**body)
    timings[f"{branch}_query_ms"] = (time.perf_counter() - started) * 1000
    # A partial ES response must not masquerade as a successful branch.
    if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
        raise RuntimeError("IncompleteElasticsearchResponse")
    hits = unique_hits(response["hits"]["hits"])
    total = response["hits"].get("total") if branch == "bm25" else None
    if isinstance(total, int):
        total = {"value": total, "relation": "eq"}
    return {"hits": hits, "timings": timings, "total": total}


def display_hit(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source", {})
    return {
        **enrich_recipe_for_display(source),
        "recipe_id": recipe_id(hit),
        "recipeid": source.get("recipeid", recipe_id(hit)),
        "document_id": str(hit.get("_id", recipe_id(hit))),
        "match_highlights": hit.get("highlight", {}), "es_source": source,
    }


def search(
    request: SearchRequest,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()

    def emit(step: str, status: str, elapsed_ms: float | None = None) -> None:
        if on_progress:
            on_progress({"type": "progress", "step": step, "status": status, "elapsed_ms": elapsed_ms})

    filters = build_filters(request)
    names = ["bm25", "vector"] if request.mode == "hybrid" else [request.mode]
    branches = {name: (lambda name=name: retrieve_candidates(request, filters, name)) for name in names}
    outcomes = execute_branches(
        branches, execution=request.execution,
        timeout_seconds=request.branch_timeout_seconds, on_progress=emit,
    )
    successful = [name for name, outcome in outcomes.items() if outcome.status == "complete"]
    if not successful:
        statuses = ", ".join(f"{name}: {value.status} ({value.error_type})" for name, value in outcomes.items())
        raise RuntimeError(f"No retrieval branch succeeded. {statuses}")

    timings: dict[str, float | None] = {
        "bm25_recall_ms": None, "vector_recall_ms": None,
        "query_embedding_ms": None, "bm25_query_ms": None, "vector_query_ms": None,
        "rrf_ms": None,
    }
    for name, outcome in outcomes.items():
        timings[f"{name}_recall_ms"] = outcome.elapsed_ms
        timings.update(outcome.timings)
    hits = {name: (outcome.hits if outcome.status == "complete" else []) for name, outcome in outcomes.items()}
    counts = {name: len(hits.get(name, [])) for name in ("bm25", "vector")}
    union_count = len({recipe_id(hit) for values in hits.values() for hit in values})
    if request.mode == "hybrid":
        emit("rrf", "running")
        fusion_started = time.perf_counter()
        fused = reciprocal_rank_fusion(hits.get("bm25", []), hits.get("vector", []),
                                       k=request.rrf_k, size=max(1, union_count),
                                       bm25_boost=request.bm25_boost, vector_boost=request.vector_boost)
        timings["rrf_ms"] = (time.perf_counter() - fusion_started) * 1000
        emit("rrf", "complete", round(timings["rrf_ms"], 2))
        rerank_started = time.perf_counter()
        fused = rerank(fused, request)
        timings["preference_rerank_ms"] = (time.perf_counter() - rerank_started) * 1000
        results = [{**display_hit(row["hit"]),
                    **{key: value for key, value in row.items() if key != "hit"},
                    "score": row["rrf_score"], "score_type": "rrf"} for row in fused[:request.size]]
        match_result_size = {"value": union_count, "relation": "eq", "scope": "candidate_union"}
    else:
        emit("rrf", "skipped")
        results = []
        for rank, hit in enumerate(hits[request.mode][:request.size], start=1):
            score = hit.get("_score")
            results.append({
                **display_hit(hit), "rank": rank, "score": score,
                "score_type": request.mode,
                **({"semantic_similarity": score * 2 - 1} if request.mode == "vector" and score is not None else {}),
            })
        match_result_size = (
            {**outcomes["bm25"].total, "scope": "lexical_matches"}
            if request.mode == "bm25" and outcomes["bm25"].total is not None
            else {"value": union_count, "relation": "eq", "scope": "candidates"}
        )
    effective_mode = "hybrid" if len(successful) == 2 else successful[0]
    warnings = []
    if request.mode == "hybrid" and effective_mode != "hybrid":
        warnings.append(f"This search used only {effective_mode.upper()} results; the other branch failed or timed out.")
    timings["search_total_ms"] = (time.perf_counter() - started) * 1000
    return {
        "query": request.query, "mode": request.mode, "effective_mode": effective_mode,
        "execution": request.execution, "result_count": len(results), "results": results,
        "match_result_size": match_result_size,
        "candidate_counts": {**counts, "union": union_count},
        "rrf": {"k": request.rrf_k, "bm25_boost": request.bm25_boost,
                "vector_boost": request.vector_boost, "bm25_candidates": request.bm25_candidates,
                "vector_candidates": request.vector_candidates,
                "vector_num_candidates": request.vector_num_candidates} if request.mode == "hybrid" else None,
        "branches": {name: {"status": outcome.status, "elapsed_ms": round(outcome.elapsed_ms, 2),
                            "candidate_count": counts[name], "error_type": outcome.error_type}
                     for name, outcome in outcomes.items()},
        "effective_filters": request.model_dump(include={"include_ingredients", "exclude_ingredients", "labels",
            "cook_time", "max_total_time_minutes", "max_calories"}),
        "preference_rules": RULES if request.mode == "hybrid" else None,
        "preferences": request.model_dump(include={"rating_boost", "preference_healthy", "preference_quick", "preference_easy", "preference_weight_healthy", "preference_weight_quick", "preference_weight_easy", "preference_weight_available", "preference_weight_prefer", "preference_weight_avoid", "preference_weight_cuisine", "preference_weight_meal_type", "preference_weight_dish_type", "preference_lambda", "preference_available", "preference_prefer", "preference_avoid", "preference_cuisine", "preference_meal_type", "preference_dish_type"}) if request.mode == "hybrid" else None,
        "warnings": warnings,
        "timings": {name: round(value, 2) if value is not None else None for name, value in timings.items()},
    }


app = FastAPI(title="Recipe Search Prototype 1.1", version="1.1.0")
app.include_router(intent_router)
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
        response = search(request)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Search failed while querying Elasticsearch.",
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
        ) from exc
    response["timings"]["backend_request_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return response


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
            response = search(request, events.put)
            response["timings"]["backend_request_ms"] = round((time.perf_counter() - started) * 1000, 2)
            events.put({"type": "result", **response})
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
