#!/usr/bin/env python3
"""Recipe search API: BM25, vector and hybrid retrieval with ingredient filters."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any, Callable, Literal

from elasticsearch import NotFoundError
from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from recipe_search.matching.constraint_logic import (
    RequiredExpression,
    default_expression,
    normalized,
    safe_pushdown,
    validate_references,
)
from recipe_search.matching.ingredient_match import expand, ingredient_clause
from recipe_search.matching.tag_expansion import expand_tags
from recipe_search.matching.time_match import time_constraint_matches
from recipe_search.matching.wordforms import distinct_groups, matching_forms
from recipe_search.presentation.recipe_display_image import (
    dedupe_borrowed_images,
    enrich_recipe_for_display,
)
from recipe_search.ranking.preference_ranking import RULES, rerank
from recipe_search.retrieval.relaxation_planner import (
    apply_actions,
    build_relaxation_aggs,
    choose_relaxation,
    choose_relaxation_set,
)
from recipe_search.retrieval.retrieval_execution import execute_branches
from recipe_search.retrieval.rrf import recipe_id, reciprocal_rank_fusion, unique_hits
from recipe_search.retrieval.search_recipes import encode_query, encode_weighted
from recipe_search.retrieval.semantic_search import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ES_URL,
    DEFAULT_INDEX,
    connect_elasticsearch,
    load_embedding_model,
)
from recipe_search.settings import PACKAGE_ROOT, get_settings

Mode = Literal["bm25", "vector", "hybrid"]
CookTime = Literal["less_30", "30_60", "60_120", "120_180", "more_180"]
ROOT = PACKAGE_ROOT
STATIC_DIR = ROOT / "web"
STATISTICS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="relaxation-statistics")
STATISTICS_SLOTS = threading.BoundedSemaphore(4)
SOURCE_EXCLUDES = [
    "extract_evidence",
    "content_vector",
    "embedding_text",
    "searchable_text",
    "instructions_text",
]


class NumericFilter(BaseModel):
    field: Literal["total_time", "calories", "protein"]
    operator: Literal["lt", "lte", "gt", "gte", "eq"]
    value: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    basis: Literal["not_applicable", "per_serving"]

    @model_validator(mode="after")
    def validate_basis(self):
        expected = "not_applicable" if self.field == "total_time" else "per_serving"
        if self.basis != expected:
            raise ValueError(
                "Nutrition filters require per-serving values; time uses not_applicable"
            )
        return self


class SearchRequest(BaseModel):
    query: Annotated[str, Field(max_length=500)] = ""
    bm25_query: Annotated[str | None, Field(max_length=500)] = None
    vector_query: Annotated[str | None, Field(max_length=500)] = None
    vector_scope_query: Annotated[str, Field(max_length=500)] = ""
    vector_scope_weight: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.30
    apply_preference_rerank: bool = True
    cuisine_target: str = ""
    cuisine_role: Literal["required", "prefer"] | None = None
    meal_type_target: str = ""
    bm25_meal_type: str = ""
    bm25_cuisine_boost: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 6.0
    mode: Mode = "hybrid"
    retrieval_strategy: Literal["text", "label_scope"] = "text"
    scope_meal_types: list[str] = Field(default_factory=list)
    scope_cuisines: list[str] = Field(default_factory=list)
    bm25_available_boost: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] = 2.0
    required_expression: RequiredExpression | None = None
    category_required: list[str] | None = None
    category_excluded: list[str] | None = None
    dish_name_target: str = ""
    dish_type_target: str = ""
    include_ingredients: list[str] = Field(default_factory=list)
    exclude_ingredients: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    numeric_filters: list[NumericFilter] = Field(default_factory=list)
    bm25_dish_name: str = ""
    bm25_dish_type: str = ""
    bm25_cuisine: str = ""
    bm25_categories: list[str] = Field(default_factory=list)
    preference_weight_available: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_weight_prefer: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_weight_avoid: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_weight_cuisine: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 3.0
    preference_weight_meal_type: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 3.0
    preference_weight_dish_type: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 2.0
    preference_healthy: list[str] = Field(default_factory=list)
    preference_weight_healthy: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_quick: list[str] = Field(default_factory=list)
    preference_weight_quick: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1.0
    preference_flavor: list[str] = Field(default_factory=list)
    preference_weight_flavor: Annotated[float, Field(ge=0, le=100)] = 1
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
    bm25_fallback_threshold: Annotated[int | None, Field(strict=True, ge=0, le=2000)] = None
    strict_candidate_threshold: Annotated[int, Field(strict=True, ge=0, le=2000)] = 10
    relaxed_candidates: Annotated[int, Field(strict=True, ge=1, le=100)] = 10
    near_miss_target: Annotated[int, Field(strict=True, ge=1, le=5)] = 5
    relaxation_strategy: Literal["single", "multi"] = "multi"
    relaxation_vector_strategy: Literal["combined", "separate"] = "combined"
    relaxation_max_plans: Annotated[int, Field(strict=True, ge=1, le=3)] = 3
    relaxation_plan_min_matches: Annotated[int, Field(strict=True, ge=1, le=100)] = 3
    relaxed_bm25_per_plan: Annotated[int, Field(strict=True, ge=1, le=20)] = 5
    relaxed_vector_k: Annotated[int, Field(strict=True, ge=1, le=100)] = 15
    relaxed_vector_num_candidates: Annotated[int, Field(strict=True, ge=15, le=10000)] = 100
    near_miss_per_group: Annotated[int, Field(strict=True, ge=1, le=3)] = 2
    relaxation_small_plan_threshold: Annotated[int, Field(strict=True, ge=0, le=20)] = 20
    relaxation_timeout_seconds: Annotated[float, Field(gt=0, le=10)] = 1.5
    core_ingredients: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def legacy_threshold(cls, data):
        if isinstance(data, dict) and data.get("bm25_fallback_threshold") is not None:
            if (
                "strict_candidate_threshold" in data
                and data["strict_candidate_threshold"] != data["bm25_fallback_threshold"]
            ):
                raise ValueError(
                    "Conflicting strict_candidate_threshold and legacy bm25_fallback_threshold"
                )
            data = {**data, "strict_candidate_threshold": data["bm25_fallback_threshold"]}
        return data

    bm25_candidates: Annotated[int, Field(strict=True, ge=1, le=2000)] = 500
    vector_candidates: Annotated[int, Field(strict=True, ge=1, le=2000)] = 500
    vector_num_candidates: Annotated[int | None, Field(strict=True, ge=1, le=10000)] = None
    bm25_boost: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 1.0
    vector_boost: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] = 2.0
    execution: Literal["parallel", "serial"] = "parallel"
    branch_timeout_seconds: Annotated[float, Field(gt=0, le=120, allow_inf_nan=False)] = 30.0

    @model_validator(mode="after")
    def validate_candidates(self) -> "SearchRequest":
        validate_references(
            self.required_expression, self.include_ingredients + (self.category_required or [])
        )
        if self.required_expression:
            from recipe_search.matching.constraint_logic import references

            if any(
                normalized(n)
                in {
                    normalized(x) for x in self.exclude_ingredients + (self.category_excluded or [])
                }
                for n in references(self.required_expression)
            ):
                raise ValueError("Required expression cannot reference an excluded ingredient")
        numeric = [(c.field, c.operator, c.value) for c in self.numeric_filters]
        if self.max_total_time_minutes is not None:
            numeric.append(("total_time", "lte", self.max_total_time_minutes))
        if self.max_calories is not None:
            numeric.append(("calories", "lte", self.max_calories))
        for field in ("total_time", "calories", "protein"):
            lowers = [
                (value, op == "gt")
                for f, op, value in numeric
                if f == field and op in ("gt", "gte", "eq")
            ]
            uppers = [
                (value, op == "lt")
                for f, op, value in numeric
                if f == field and op in ("lt", "lte", "eq")
            ]
            low = max(lowers, default=None)
            high = min(uppers, key=lambda b: (b[0], not b[1])) if uppers else None
            if low and high and (low[0] > high[0] or low[0] == high[0] and (low[1] or high[1])):
                raise ValueError("Conflicting " + field + " limits; clarify the intended range")
        if self.bm25_query is None:
            self.bm25_query = self.query
        if self.vector_query is None:
            self.vector_query = self.query
        if self.mode != "vector" and self.retrieval_strategy == "text" and not self.bm25_query:
            raise ValueError("BM25 text retrieval requires a nonempty bm25_query")
        if self.mode != "bm25" and not self.vector_query:
            raise ValueError("Vector embedding requires a nonempty vector_query")
        if self.retrieval_strategy == "label_scope" or self.scope_meal_types or self.scope_cuisines:
            raise ValueError(
                "Label scope is retired. Use ranking preferences and independent final cuisine conditions."
            )
        if self.mode == "hybrid" and min(self.bm25_candidates, self.vector_candidates) < self.size:
            raise ValueError("Each hybrid candidate count must be at least size")
        if self.vector_num_candidates is None:
            self.vector_num_candidates = max(250, self.vector_candidates)
        vector_count = self.vector_candidates
        if self.mode != "bm25" and self.vector_num_candidates < vector_count:
            raise ValueError("vector_num_candidates must be at least the vector result count")
        return self

    @field_validator("query", "bm25_query", "vector_query")
    @classmethod
    def strip_query(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("bm25_categories")
    @classmethod
    def normalize_bm25_categories(cls, values):
        return list(dict.fromkeys(normalize_category(value) for value in values if value.strip()))

    @field_validator("include_ingredients", "exclude_ingredients")
    @classmethod
    def clean_ingredients(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator(
        "scope_meal_types",
        "scope_cuisines",
        "preference_healthy",
        "preference_quick",
        "preference_easy",
        "preference_flavor",
        "labels",
        "preference_available",
        "preference_prefer",
        "preference_avoid",
        "preference_cuisine",
        "preference_meal_type",
        "preference_dish_type",
    )
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

    return {
        "bool": {
            "filter": [ingredient_clause(n) for n in include],
            "must_not": [
                ingredient_clause(n, excluded=True)
                for n in exclude
                if any(expand(n, field) for field in ("ingredients", "extract_ingredients"))
            ],
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
    return (
        {
            "range": {
                "total_time_minutes": {
                    **ranges[value],
                    **(
                        {"gt": 0}
                        if "gt" not in ranges[value] and "gte" not in ranges[value]
                        else {}
                    ),
                }
            }
        }
        if value
        else None
    )


def build_filters(request: SearchRequest) -> dict[str, Any] | None:
    ingredient = ingredient_filters([], request.exclude_ingredients)
    if ingredient is None:
        ingredient = {"bool": {"filter": [], "must_not": []}}
    expr = request.required_expression or default_expression(
        request.include_ingredients + (request.category_required or [])
    )
    condition = safe_pushdown(
        expr, {normalized(n) for n in request.category_required or []}, ingredient_clause
    )
    if condition:
        ingredient["bool"]["filter"].append(condition)
    total_time_bucket = total_time_bucket_filter(request.cook_time)
    numeric_filters: list[dict[str, Any]] = []
    for condition in request.numeric_filters:
        field = {
            "total_time": "total_time_minutes",
            "calories": "calories",
            "protein": "proteincontent",
        }[condition.field]
        numeric_filters.append({"exists": {"field": field}})
        bounds = (
            {"gte": condition.value, "lte": condition.value}
            if condition.operator == "eq"
            else {condition.operator: condition.value}
        )
        numeric_filters.append({"range": {field: bounds}})
        if condition.field == "total_time":
            numeric_filters.append({"range": {field: {"gt": 0}}})
    if request.labels:
        numeric_filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {field: {"value": label, "case_insensitive": True}}}
                        for label in request.labels
                        for field in ("recipecategory", "keywords")
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if request.max_total_time_minutes is not None:
        numeric_filters.extend(
            [
                {"exists": {"field": "total_time_minutes"}},
                {"range": {"total_time_minutes": {"gt": 0, "lte": request.max_total_time_minutes}}},
            ]
        )
    if request.max_calories is not None:
        numeric_filters.extend(
            [
                {"exists": {"field": "calories"}},
                {"range": {"calories": {"lte": request.max_calories}}},
            ]
        )
    if not ingredient and not total_time_bucket and not numeric_filters:
        return None
    return {
        "bool": {
            "filter": (ingredient or {"bool": {}}).get("bool", {}).get("filter", [])
            + ([total_time_bucket] if total_time_bucket else [])
            + numeric_filters,
            "must_not": (ingredient or {"bool": {}}).get("bool", {}).get("must_not", []),
        }
    }


def normalize_category(value: str) -> str:
    value = value.strip().casefold()
    aliases = {
        "vegetabels": "vegetable",
        "vegetabel": "vegetable",
        "vegatables": "vegetable",
        "vegatable": "vegetable",
        "vegetables": "vegetable",
        "veggies": "vegetable",
        "meats": "meat",
        "seafoods": "seafood",
        "fruits": "fruit",
        "legumes": "legume",
        "grains": "grain",
        "nuts": "nut",
    }
    return aliases.get(value, value)


def bm25_query(
    query: str, filters: dict[str, Any] | None, request: SearchRequest | None = None
) -> dict[str, Any]:
    lexical_match: dict[str, Any] = {
        "multi_match": {
            "query": query,
            "fields": [
                "name^5",
                "keywords^3",
                "ingredients^2",
                "extract_ingredients_firm^2",
                "description^2",
                "searchable_text",
            ],
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
        "constant_score": {
            "filter": {
                "match_phrase": {
                    "name": request.bm25_dish_name.strip()
                    if request and request.bm25_dish_name.strip()
                    else query
                }
            },
            "boost": 12,
            "_name": "dish_name_phrase",
        }
    }
    bool_query: dict[str, Any] = {
        "must": [lexical_match],
        "should": [title_phrase_boost],
        "minimum_should_match": 0,
    }
    if request:

        def reward(condition, boost, name):
            bool_query["should"].append(
                {"constant_score": {"filter": condition, "boost": boost, "_name": name}}
            )

        for name, value, boost in [
            ("dish_type", request.bm25_dish_type, 5),
            ("cuisine", request.bm25_cuisine, request.bm25_cuisine_boost),
        ]:
            value = value.strip().casefold()
            if value:
                reward(
                    {
                        "bool": {
                            "should": [
                                {"terms": {field: matching_forms(field, value)}}
                                if name == "dish_type"
                                else {"term": {field: value}}
                                for field in ("keywords", "recipecategory")
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                    boost,
                    name,
                )
        seen_ingredient_groups = set()
        for index, name in enumerate(request.include_ingredients):
            clause = ingredient_clause(name)
            signature = json.dumps(clause, sort_keys=True)
            if signature in seen_ingredient_groups or "match_none" in clause:
                continue
            seen_ingredient_groups.add(signature)
            reward(clause, 2, f"required_ingredient_{index}")
        for index, name in enumerate(request.preference_available):
            if request.bm25_available_boost > 0:
                reward(
                    ingredient_clause(name),
                    request.bm25_available_boost,
                    f"available_ingredient_{index}",
                )
        meal_rewards = []
        for index, (tag, weight) in enumerate(expand_tags("meal_types", request.bm25_meal_type)):
            if tag:
                meal_rewards.append(
                    {
                        "constant_score": {
                            "filter": {
                                "bool": {
                                    "should": [
                                        {"term": {field: tag}}
                                        for field in ("keywords", "recipecategory")
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                            "boost": 2 * weight,
                            "_name": f"meal_type_{index}",
                        }
                    }
                )
        if meal_rewards:
            bool_query["should"].append({"dis_max": {"queries": meal_rewards, "tie_breaker": 0}})
        for index, forms in enumerate(
            distinct_groups(
                "keywords", [normalize_category(item) for item in request.bm25_categories]
            )
        ):
            reward({"terms": {"keywords": forms}}, 2, f"ingredient_category_{index}")
    if filters:
        bool_query["filter"] = filters["bool"]["filter"]
        bool_query["must_not"] = filters["bool"]["must_not"]
    return {"bool": bool_query}


def retrieve_candidates(
    request: SearchRequest,
    filters: dict[str, Any] | None,
    branch: str,
) -> dict[str, Any]:
    """One independent ES request with the explicitly supplied branch filters."""
    count = request.bm25_candidates if branch == "bm25" else request.vector_candidates
    body: dict[str, Any] = {
        "index": DEFAULT_INDEX,
        "size": count,
        "track_total_hits": branch == "bm25",
        "source": {
            "excludes": SOURCE_EXCLUDES
            + ["instructions", "extract_ingredient_evidence", "extract_ingredients_evidence"]
        },
    }
    timings: dict[str, float] = {}
    if branch == "bm25":
        body["query"] = bm25_query(request.bm25_query, filters, request)
        body["highlight"] = {
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
            "fields": {
                "name": {"number_of_fragments": 0},
                "keywords": {"number_of_fragments": 0},
                "ingredients": {"number_of_fragments": 0},
                "extract_ingredients": {"number_of_fragments": 0},
                "description": {"fragment_size": 160, "number_of_fragments": 1},
            },
        }
    else:
        started = time.perf_counter()
        state = getattr(request, "_relax_embedding_state", None)

        def embed():
            return (
                encode_weighted(
                    get_model(),
                    request.vector_query,
                    request.vector_scope_query,
                    beta=request.vector_scope_weight,
                )
                if request.vector_scope_query.strip() and request.vector_scope_weight
                else encode_query(get_model(), request.vector_query)
            )

        if state is None:
            vector = embed()
        else:
            # Shared even when strict recall times out while its embedding runs.
            with state["lock"]:
                if state["vector"] is None:
                    state["vector"] = embed()
                vector = state["vector"]
        timings["query_embedding_ms"] = (time.perf_counter() - started) * 1000
        body["knn"] = {
            "field": "content_vector",
            "query_vector": vector,
            "k": count,
            "num_candidates": request.vector_num_candidates,
        }
        if filters:
            body["knn"]["filter"] = filters

    started = time.perf_counter()
    trace = {
        "branch": branch,
        "attempt": "initial",
        "body": copy.deepcopy(body),
        "semantic_query": request.vector_query if branch == "vector" else None,
        "semantic_scope_query": request.vector_scope_query if branch == "vector" else None,
        "vector_scope_weight": request.vector_scope_weight,
        "settings": request.model_dump(
            exclude={"retrieval_strategy", "scope_meal_types", "scope_cuisines"}
        ),
        "timings": dict(timings),
    }
    try:
        response = (
            get_client()
            .options(
                request_timeout=request.branch_timeout_seconds,
                max_retries=0,
            )
            .search(**body)
        )
    except Exception as error:
        trace["error_type"] = type(error).__name__
        error.query_trace = [trace]
        raise
    timings[f"{branch}_query_ms"] = (time.perf_counter() - started) * 1000
    processing_started = time.perf_counter()
    timings[f"{branch}_es_took_ms"] = response.get("took", 0)
    # A partial ES response must not masquerade as a successful branch.
    if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
        raise RuntimeError("IncompleteElasticsearchResponse")
    hits = unique_hits(response["hits"]["hits"])
    total = response["hits"].get("total") if branch == "bm25" else None
    if isinstance(total, int):
        total = {"value": total, "relation": "eq"}
    timings[f"{branch}_response_processing_ms"] = (time.perf_counter() - processing_started) * 1000
    return {
        "hits": hits,
        "timings": timings,
        "total": total,
        "query_trace": [{**trace, "timings": dict(timings)}],
    }


def display_hit(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source", {})
    return {
        **enrich_recipe_for_display(source),
        "recipe_id": recipe_id(hit),
        "recipeid": source.get("recipeid", recipe_id(hit)),
        "document_id": str(hit.get("_id", recipe_id(hit))),
        "match_highlights": hit.get("highlight", {}),
        "bm25_matched_queries": hit.get("matched_queries", []),
    }


def search(
    request: SearchRequest,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()

    def emit(step: str, status: str, elapsed_ms: float | None = None, **extra) -> None:
        if on_progress:
            on_progress(
                {
                    "type": "progress",
                    "step": step,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    **extra,
                }
            )

    object.__setattr__(
        request, "_relax_embedding_state", {"lock": threading.Lock(), "vector": None}
    )
    filters = build_filters(request)
    filter_preparation_ms = (time.perf_counter() - started) * 1000
    names = ["bm25", "vector"] if request.mode == "hybrid" else [request.mode]
    stats_body, variants, protected = build_relaxation_aggs(request, build_filters)
    stats_body["index"] = DEFAULT_INDEX
    relaxation = dict(
        status="not_needed",
        threshold=request.strict_candidate_threshold,
        relaxed_candidates=request.relaxed_candidates,
        strategy=request.relaxation_strategy,
        plan_min_matches=request.relaxation_plan_min_matches,
        protected_conditions=protected,
        plans=variants,
        selected_plans=[],
        selected_plan=None,
        original_conditions=request.model_dump(),
        statistics={},
        executions={},
    )

    def statistics():
        tick = time.perf_counter()
        emit("relaxation_statistics", "running")
        try:
            response = (
                get_client()
                .options(request_timeout=0.9, max_retries=0)
                .search(**stats_body, request_cache=True)
            )
            if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
                raise RuntimeError("Incomplete relaxation statistics")
            buckets = response["aggregations"]["relaxation_plans"]["buckets"]
            counts = {
                key: buckets[key]["doc_count"]
                for key in ["strict"] + [p["plan_id"] for p in variants]
            }
            if any(not isinstance(v, int) or v < 0 for v in counts.values()):
                raise ValueError("Invalid aggregation counts")
            return dict(
                status="complete",
                counts=counts,
                elapsed_ms=(time.perf_counter() - tick) * 1000,
                dsl=stats_body,
                missing_numeric={
                    k: v["doc_count"]
                    for k, v in response.get("aggregations", {}).get("missing_numeric", {}).items()
                    if isinstance(v, dict) and "doc_count" in v
                },
            )
        except Exception as error:
            return dict(
                status="failed",
                error_type=type(error).__name__,
                elapsed_ms=(time.perf_counter() - tick) * 1000,
                dsl=stats_body,
            )

    stat_future = None
    stats_busy = False
    if variants and request.strict_candidate_threshold:
        if STATISTICS_SLOTS.acquire(blocking=False):
            stat_future = STATISTICS_POOL.submit(statistics)
            stat_future.add_done_callback(lambda _: STATISTICS_SLOTS.release())
        else:
            stats_busy = True
    strict_counts = {}

    def strict_progress(name, status, elapsed_ms=None):
        emit(
            name,
            status,
            elapsed_ms,
            **(
                {"candidate_count": strict_counts[name]}
                if status == "complete" and name in strict_counts
                else {}
            ),
        )

    def strict_retrieve(name):
        result = copy.deepcopy(retrieve_candidates(request, filters, name))
        for hit in result["hits"]:
            hit["source_level"] = "strict"
            hit["bm25_source_level"] = "original" if name == "bm25" else None
        strict_counts[name] = len(result["hits"])
        return result

    branches = {name: (lambda name=name: strict_retrieve(name)) for name in names}
    outcomes = execute_branches(
        branches,
        execution=request.execution,
        timeout_seconds=request.branch_timeout_seconds,
        on_progress=strict_progress,
    )
    strict_snapshots = {
        name: dict(status=o.status, hits=copy.deepcopy(o.hits), elapsed_ms=o.elapsed_ms)
        for name, o in outcomes.items()
    }
    strict_ids = {
        recipe_id(h)
        for outcome in outcomes.values()
        if outcome.status == "complete"
        for h in outcome.hits
    }
    relaxation["strict_candidate_count"] = len(strict_ids)
    relaxation["strict_branches"] = {
        n: dict(returned=len(o.hits), elapsed_ms=o.elapsed_ms, status=o.status)
        for n, o in outcomes.items()
    }
    emit(
        "strict_candidate_check",
        "complete",
        candidate_count=len(strict_ids),
        threshold=request.strict_candidate_threshold,
    )
    statistics_result = (
        dict(status="failed", error_type="StatisticsCapacityExceeded") if stats_busy else {}
    )
    if stat_future:
        try:
            statistics_result = stat_future.result(timeout=0.95)
        except FutureTimeout:
            statistics_result = dict(status="timeout", error_type="StatisticsDeadline")
    if stat_future and not stat_future.done():
        stat_future.cancel()
    relaxation["statistics"] = statistics_result
    emit(
        "relaxation_statistics",
        statistics_result.get("status", "skipped"),
        statistics_result.get("elapsed_ms"),
    )
    relaxed_outcomes = {}
    selected = None
    if (
        not request.strict_candidate_threshold
        or len(strict_ids) >= request.strict_candidate_threshold
    ):
        relaxation.update(status="strict_sufficient", reason="Strict candidates meet the threshold")
    elif not variants:
        relaxation.update(
            status="no_plan", reason="Only protected or unsupported conditions remain"
        )
    elif statistics_result.get("status") != "complete":
        relaxation.update(
            status="statistics_failed", reason="Statistics unavailable; strict results retained"
        )
    else:
        if request.relaxation_strategy == "multi":
            selected_plans = choose_relaxation_set(
                variants,
                statistics_result["counts"],
                request.relaxation_plan_min_matches,
                request.relaxation_max_plans,
            )
            selected = selected_plans[0] if selected_plans else None
            relaxation["selected_plans"] = selected_plans
            if not selected:
                relaxation.update(
                    status="no_plan", reason="No distinct plan meets the per-plan minimum"
                )
            else:
                from recipe_search.retrieval.multi_relaxation import execute_relaxed

                relaxation.update(
                    status="running",
                    selected_plan=selected,
                    reason="Distinct relaxation directions",
                    core_ingredient_notice=[
                        dict(
                            ingredient=a["value"],
                            strict_count=len(strict_ids),
                            scope="retrieved_candidates",
                        )
                        for p in selected_plans
                        for a in p["actions"]
                        if a.get("sole_required_exception")
                    ],
                )
                emit("relaxation_decision", "complete", plan=selected, plans=selected_plans)
                executions = execute_relaxed(request, selected_plans, names, strict_ids, emit)
                relaxation["executions"] = executions
                for name, run in executions.items():
                    original = outcomes[name]
                    if run["hits"]:
                        original.hits = unique_hits(original.hits + run["hits"])
                        original.status = "complete"
                    original.query_trace += run["query_trace"]
                    original.elapsed_ms += run["elapsed_ms"]
                relaxation["status"] = (
                    "complete"
                    if all(r["status"] == "complete" for r in executions.values())
                    else "partial"
                    if any(r["hits"] for r in executions.values())
                    else "failed"
                )
                relaxation["executions"] = {
                    name: {k: v for k, v in run.items() if k not in ("hits", "query_trace")}
                    for name, run in executions.items()
                }
        else:
            selected = choose_relaxation(
                variants, statistics_result["counts"], request.relaxed_candidates
            )
            if not selected:
                relaxation.update(
                    status="no_plan", reason="No allowed plan reaches the filter-range target"
                )
            else:
                relaxed = apply_actions(request, selected["actions"]).model_copy(
                    update={
                        "bm25_candidates": request.relaxed_candidates,
                        "vector_candidates": request.relaxed_candidates,
                    }
                )
                relaxed_filters = build_filters(relaxed)
                relaxation["core_ingredient_notice"] = [
                    dict(
                        ingredient=a["value"],
                        strict_count=len(strict_ids),
                        scope="retrieved_candidates",
                    )
                    for a in selected["actions"]
                    if a.get("sole_required_exception")
                ]
                relaxation.update(
                    status="running",
                    selected_plan=selected,
                    effective_conditions=relaxed.model_dump(),
                    reason=selected["reason"],
                )
                emit("relaxation_decision", "complete", plan=selected)
                relaxed_counts = {}

                def relaxed_progress(name, status, elapsed_ms=None):
                    emit(
                        "relaxed_" + name,
                        status,
                        elapsed_ms,
                        **(relaxed_counts.get(name, {}) if status == "complete" else {}),
                    )

                def relaxed_retrieve(name):
                    result = copy.deepcopy(retrieve_candidates(relaxed, relaxed_filters, name))
                    for hit in result["hits"]:
                        hit.update(
                            source_level="relaxed",
                            relaxation=selected["actions"],
                            bm25_source_level="relaxed" if name == "bm25" else None,
                        )
                    result["query_trace"] = [
                        {**t, "attempt": "relaxed"} for t in result.get("query_trace", [])
                    ]
                    relaxed_counts[name] = dict(
                        candidate_count=len(result["hits"]),
                        added=sum(recipe_id(h) not in strict_ids for h in result["hits"]),
                    )
                    return result

                relaxed_outcomes = execute_branches(
                    {name: (lambda name=name: relaxed_retrieve(name)) for name in names},
                    execution=request.execution,
                    timeout_seconds=request.branch_timeout_seconds,
                    on_progress=relaxed_progress,
                )
                for name, outcome in relaxed_outcomes.items():
                    relaxation["executions"][name] = dict(
                        status=outcome.status,
                        elapsed_ms=outcome.elapsed_ms,
                        returned=len(outcome.hits),
                        added=sum(recipe_id(h) not in strict_ids for h in outcome.hits),
                        error_type=outcome.error_type,
                    )
                    if outcome.status == "complete":
                        original = outcomes[name]
                        original.hits = unique_hits(original.hits + outcome.hits)
                        original.query_trace += outcome.query_trace
                        original.elapsed_ms += outcome.elapsed_ms
                        if original.status != "complete":
                            original.status = "complete"
                relaxation["status"] = (
                    "complete"
                    if all(o.status == "complete" for o in relaxed_outcomes.values())
                    else "partial"
                    if any(o.status == "complete" for o in relaxed_outcomes.values())
                    else "failed"
                )
    emit("relaxation_decision", relaxation["status"], strict_count=len(strict_ids))
    fallback_info = dict(
        triggered=False, used=False, status="retired", threshold=request.strict_candidate_threshold
    )
    successful = [name for name, outcome in outcomes.items() if outcome.status == "complete"]
    if not successful:
        statuses = ", ".join(
            f"{name}: {value.status} ({value.error_type})" for name, value in outcomes.items()
        )
        raise RuntimeError(f"No retrieval branch succeeded. {statuses}")

    timings: dict[str, float | None] = {
        "bm25_recall_ms": None,
        "vector_recall_ms": None,
        "query_embedding_ms": None,
        "bm25_query_ms": None,
        "vector_query_ms": None,
        "rrf_ms": None,
        "filter_preparation_ms": filter_preparation_ms,
    }
    for name, outcome in outcomes.items():
        timings[f"{name}_recall_ms"] = outcome.elapsed_ms
        timings.update(outcome.timings)
    hits = {
        name: (outcome.hits if outcome.status == "complete" else [])
        for name, outcome in outcomes.items()
    }
    counts = {name: len(hits.get(name, [])) for name in ("bm25", "vector")}
    union_count = len({recipe_id(hit) for values in hits.values() for hit in values})
    rrf_output_count = None
    emit("candidate_merge", "complete", candidate_count=union_count)
    emit("rrf", "running" if request.mode == "hybrid" else "skipped")
    fusion_ms = 0.0
    rerank_ms = 0.0
    fused = []
    for layer in ("strict", "relaxed"):
        branch_hits = {
            name: [
                h
                for h in rows
                if (
                    h.get("source_level") == "strict"
                    if layer == "strict"
                    else recipe_id(h) not in strict_ids
                )
            ]
            for name, rows in hits.items()
        }
        tick = time.perf_counter()
        if request.mode == "hybrid":
            rows = reciprocal_rank_fusion(
                branch_hits.get("bm25", []),
                branch_hits.get("vector", []),
                k=request.rrf_k,
                size=100,
                bm25_boost=request.bm25_boost,
                vector_boost=request.vector_boost,
            )
        else:
            rows = [
                dict(hit=h, rank=rank, rrf_score=1 / (request.rrf_k + rank))
                for rank, h in enumerate(branch_hits.get(request.mode, [])[:100], 1)
            ]
        fusion_ms += (time.perf_counter() - tick) * 1000
        tick = time.perf_counter()
        if request.apply_preference_rerank:
            rows = rerank(rows, request)
        rerank_ms += (time.perf_counter() - tick) * 1000
        fused += rows
    fused = fused[:100]
    for rank, row in enumerate(fused, 1):
        row["rank"] = rank
    timings["rrf_ms"] = fusion_ms if request.mode == "hybrid" else None
    timings["preference_rerank_ms"] = rerank_ms
    if request.mode == "hybrid":
        emit("rrf", "complete", timings["rrf_ms"], candidate_count=len(fused))
        rrf_output_count = len(fused)
    results = dedupe_borrowed_images(
        [
            {
                **display_hit(row["hit"]),
                **{k: v for k, v in row.items() if k != "hit"},
                "score": row["rrf_score"] if request.mode == "hybrid" else row["hit"].get("_score"),
                "score_type": "rrf" if request.mode == "hybrid" else request.mode,
            }
            for row in fused[: request.size]
        ]
    )
    match_result_size = {
        "value": union_count,
        "relation": "eq",
        "scope": "candidate_union" if request.mode == "hybrid" else "candidates",
    }
    if request.mode == "bm25" and outcomes["bm25"].total is not None:
        match_result_size = {**outcomes["bm25"].total, "scope": "lexical_matches"}
    metadata = {}
    for values in hits.values():
        for h in values:
            identifier = recipe_id(h)
            strict = identifier in strict_ids
            meta = metadata.setdefault(
                identifier,
                dict(
                    source_level="strict" if strict else "relaxed",
                    relaxation=[],
                    source_plans=[],
                    relaxation_plans=[],
                    relaxation_cost=0,
                ),
            )
            if not strict:
                plans = h.get("relaxation_plans") or ([selected] if selected else [])
                for plan in plans:
                    if plan["plan_id"] not in meta["source_plans"]:
                        meta["source_plans"].append(plan["plan_id"])
                        meta["relaxation_plans"].append(
                            {k: plan[k] for k in ("plan_id", "actions", "cost")}
                        )
                meta["relaxation_cost"] = min(
                    (p["cost"] for p in meta["relaxation_plans"]), default=0
                )
                meta["relaxation"] = list(
                    {
                        json.dumps(a, sort_keys=True): a
                        for p in meta["relaxation_plans"]
                        for a in p["actions"]
                    }.values()
                )
    for result in results:
        result.update(metadata[result["recipe_id"]])
        if request.mode == "vector" and result.get("score") is not None:
            result["semantic_similarity"] = result["score"] * 2 - 1
    source_levels = {
        recipe_id(h): h.get("bm25_source_level", "original") for h in hits.get("bm25", [])
    }
    vector_levels = {recipe_id(h): h.get("source_level", "strict") for h in hits.get("vector", [])}
    vector_ids = set(vector_levels)
    for result in results:
        result["bm25_source_level"] = source_levels.get(result["recipe_id"])
        result["vector_matched"] = result["recipe_id"] in vector_ids
        result["vector_source_level"] = vector_levels.get(result["recipe_id"])
        result["time_constraint_matches"] = time_constraint_matches(result, request)
    effective_mode = "hybrid" if len(successful) == 2 else successful[0]
    warnings = []
    unapplied_exclusions = [
        name
        for name in request.exclude_ingredients
        if not any(expand(name, field) for field in ("ingredients", "extract_ingredients"))
    ]
    for name in unapplied_exclusions:
        warnings.append(
            f'Excluded ingredient "{name}" has no matches in the local vocabulary. No ES exclusion was applied for this ingredient; final ingredient checks remain active. Rebuild the vocabulary if data changed.'
        )
    if relaxation["status"] in ("statistics_failed", "failed", "partial", "no_plan"):
        warnings.append(
            "Recall relaxation: "
            + relaxation.get("reason", relaxation["status"])
            + ". Original eligibility conditions remain active."
        )
    if request.mode == "hybrid" and effective_mode != "hybrid":
        warnings.append(
            f"This search used only {effective_mode.upper()} results; the other branch failed or timed out."
        )
    timings["search_total_ms"] = (time.perf_counter() - started) * 1000
    # Return raw branch order alongside fusion so the UI never infers recall
    # lists from RRF or preference-ranked results. No extra ES requests.
    branch_results = {}
    for branch in names:
        raw_rows = []
        for rank, hit in enumerate(hits.get(branch, [])[: request.size], 1):
            row = {
                **display_hit(hit),
                **metadata[recipe_id(hit)],
                "rank": rank,
                "score": hit.get("_score"),
                "score_type": branch,
                "bm25_source_level": source_levels.get(recipe_id(hit)),
                "vector_matched": recipe_id(hit) in vector_ids,
                "vector_source_level": vector_levels.get(recipe_id(hit)),
            }
            if branch == "vector" and hit.get("_score") is not None:
                row["semantic_similarity"] = hit["_score"] * 2 - 1
            row["time_constraint_matches"] = time_constraint_matches(row, request)
            raw_rows.append(row)
        dedupe_borrowed_images(raw_rows)
        branch_results[branch] = {
            "status": outcomes[branch].status,
            "candidate_count": counts[branch],
            "results": raw_rows,
            "generation_candidate_ids": [recipe_id(h) for h in hits.get(branch, [])[:100]],
            "generation_candidate_levels": {
                recipe_id(h): metadata[recipe_id(h)] for h in hits.get(branch, [])[:100]
            },
        }
    if selected:
        for branch in names:
            before = strict_snapshots[branch]
            if before["status"] != "complete" or relaxation.get("executions", {}).get(
                branch, {}
            ).get("status") not in ("complete", "partial"):
                continue
            baseline_rows = []
            for rank, hit in enumerate(before["hits"][: request.size], 1):
                row = {
                    **display_hit(hit),
                    "rank": rank,
                    "score": hit.get("_score"),
                    "score_type": branch,
                    "source_level": "strict",
                    "bm25_source_level": "original" if branch == "bm25" else None,
                    "vector_matched": branch == "vector",
                    "vector_source_level": "strict" if branch == "vector" else None,
                }
                baseline_rows.append(row)
            dedupe_borrowed_images(baseline_rows)
            branch_results[branch]["strict_baseline"] = dict(
                status="complete",
                candidate_count=len(before["hits"]),
                results=baseline_rows,
                elapsed_ms=before["elapsed_ms"],
            )
    return {
        "relaxation": relaxation,
        "query": request.query,
        "bm25_query": request.bm25_query,
        "vector_query": request.vector_query,
        "mode": request.mode,
        "effective_mode": effective_mode,
        "original_conditions": request.model_dump(
            exclude={"retrieval_strategy", "scope_meal_types", "scope_cuisines"}
        ),
        "executed_queries": {name: outcome.query_trace for name, outcome in outcomes.items()},
        "execution": request.execution,
        "result_count": len(results),
        "results": results,
        "match_result_size": match_result_size,
        "branch_results": branch_results,
        "generation_candidate_levels": {
            recipe_id(row["hit"]): {
                **metadata[recipe_id(row["hit"])],
                "bm25": source_levels.get(recipe_id(row["hit"])),
                "vector": recipe_id(row["hit"]) in vector_ids,
            }
            for row in fused
        },
        "generation_candidate_ids": [recipe_id(row["hit"]) for row in fused],
        "bm25_fallback": {
            **fallback_info,
            "branch_status": outcomes["bm25"].status if "bm25" in outcomes else "not_used",
        },
        "branch_filters": {
            name: {
                "include_ingredients": request.include_ingredients,
                "exclude_ingredients": request.exclude_ingredients,
            }
            for name in names
        },
        "candidate_counts": {
            **counts,
            "union": union_count,
            "rrf": rrf_output_count,
            "by_source_level": {
                level: sum(value == level for value in source_levels.values())
                for level in ("original", "relaxed")
            },
        },
        "rrf": {
            "top_k": 100,
            "k": request.rrf_k,
            "bm25_boost": request.bm25_boost,
            "vector_boost": request.vector_boost,
            "bm25_candidates": request.bm25_candidates,
            "vector_candidates": request.vector_candidates,
            "vector_num_candidates": request.vector_num_candidates,
        }
        if request.mode == "hybrid"
        else None,
        "branches": {
            name: {
                "status": outcome.status,
                "elapsed_ms": round(outcome.elapsed_ms, 2),
                "candidate_count": counts[name],
                "error_type": outcome.error_type,
            }
            for name, outcome in outcomes.items()
        },
        "effective_filters": request.model_dump(
            include={
                "cuisine_target",
                "cuisine_role",
                "meal_type_target",
                "include_ingredients",
                "exclude_ingredients",
                "required_expression",
                "category_required",
                "category_excluded",
                "dish_name_target",
                "dish_type_target",
                "labels",
                "cook_time",
                "max_total_time_minutes",
                "max_calories",
                "numeric_filters",
            }
        ),
        "bm25_matching": request.model_dump(
            include={
                "bm25_dish_name",
                "bm25_dish_type",
                "bm25_cuisine",
                "bm25_categories",
                "bm25_available_boost",
                "bm25_cuisine_boost",
                "preference_available",
            }
        )
        if "bm25" in names
        else None,
        "preference_rules": RULES if request.apply_preference_rerank else None,
        "preferences": request.model_dump(
            include={
                "preference_flavor",
                "preference_weight_flavor",
                "rating_boost",
                "preference_healthy",
                "preference_quick",
                "preference_easy",
                "preference_weight_healthy",
                "preference_weight_quick",
                "preference_weight_easy",
                "preference_weight_available",
                "preference_weight_prefer",
                "preference_weight_avoid",
                "preference_weight_cuisine",
                "preference_weight_meal_type",
                "preference_weight_dish_type",
                "preference_lambda",
                "preference_available",
                "preference_prefer",
                "preference_avoid",
                "preference_cuisine",
                "preference_meal_type",
                "preference_dish_type",
            }
        )
        if request.apply_preference_rerank
        else None,
        "unapplied_exclusions": unapplied_exclusions,
        "warnings": warnings,
        "timings": {
            name: round(value, 2) if value is not None else None for name, value in timings.items()
        },
    }


WARMUP_STATE = dict(status="not_started")


def warmup_retrieval():
    """One local embedding + bounded ES vector read; no paid model API calls."""
    started = time.perf_counter()
    WARMUP_STATE.clear()
    if not get_settings().recipe_warmup:
        WARMUP_STATE.update(status="disabled")
        return
    WARMUP_STATE.clear()
    WARMUP_STATE.update(status="running")
    try:
        result = retrieve_candidates(
            SearchRequest(
                query="vegetable soup",
                mode="vector",
                vector_candidates=5,
                vector_num_candidates=100,
            ),
            None,
            "vector",
        )
        WARMUP_STATE.update(status="complete", timings=result.get("timings", {}))
    except Exception as exc:
        WARMUP_STATE.update(status="failed", error_type=type(exc).__name__)
        logging.getLogger("uvicorn.error").warning(
            "Retrieval warmup failed (%s); service remains available", type(exc).__name__
        )
    WARMUP_STATE["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    logging.getLogger("uvicorn.error").info("Retrieval warmup: %s", WARMUP_STATE)


@asynccontextmanager
async def lifespan(application):
    await asyncio.to_thread(warmup_retrieval)
    yield


from fastapi import APIRouter

router = APIRouter()


@router.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/health")
@router.get("/api/health", include_in_schema=False)
def health() -> dict[str, Any]:
    try:
        if not get_client().ping():
            raise RuntimeError("Elasticsearch ping returned false")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Elasticsearch is unavailable") from exc
    return {"status": "ok", "elasticsearch": "available", "retrieval_warmup": dict(WARMUP_STATE)}


@router.post("/recipes/search")
@router.post("/api/search", include_in_schema=False)
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


@router.get("/recipes/{recipe_id}")
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


@router.post("/api/search/stream")
def api_search_stream(request: SearchRequest) -> StreamingResponse:
    """Send actual retrieval stage transitions to the prototype UI over SSE."""
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def worker() -> None:
        started = time.perf_counter()
        try:
            response = search(request, events.put)
            response["timings"]["backend_request_ms"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
            events.put({"type": "result", **response})
        except Exception as exc:
            events.put(
                {
                    "type": "error",
                    "message": "Search failed while querying Elasticsearch.",
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                }
            )
        finally:
            events.put(None)

    def stream() -> Any:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while (event := events.get()) is not None:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
