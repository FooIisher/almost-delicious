"""Observable JEV adapter using the existing model experiment as source of truth.

This endpoint parses only. It never mutates filters or runs a recipe search.
"""

from __future__ import annotations
from recipe_search.settings import get_settings
from recipe_search.llm.intent_usage import usage_metrics

import hashlib
import math
from pathlib import Path
import threading
import time
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

# The CLI's jev_test imports intent_schema by its original top-level name.
# Reuse both original modules instead of maintaining another set of prompts.
MODEL_DIR = Path(__file__).resolve().parent / "jev"
import recipe_search.llm.jev.jev_test as jev
import recipe_search.llm.jev.intent_schema as schema

router = APIRouter()
PARSE_SLOTS = threading.BoundedSemaphore(4)
THRESHOLD = 0.8
TIMEOUT_SECONDS = 30
SCHEMA_VERSION = "1.1-intent-view-v1"
PROMPT_VERSION = (
    "intent-schema-"
    + hashlib.sha256(
        (MODEL_DIR / "intent_schema.py").read_bytes() + (MODEL_DIR / "jev_test.py").read_bytes()
    ).hexdigest()[:12]
)


class ContextRecipe(BaseModel):
    id: Annotated[str, Field(strict=True, min_length=1, max_length=200)]
    name: Annotated[str, Field(strict=True, min_length=1, max_length=500)]


class IntentContext(BaseModel):
    recipes: list[ContextRecipe] = Field(default_factory=list, max_length=20)
    selected_recipe_id: str | None = None

    @model_validator(mode="after")
    def validate_references(self):
        schema.validate_context(self.model_dump())
        return self


class IntentRequest(BaseModel):
    query: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    context: IntentContext = Field(default_factory=IntentContext)

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, query):
        if not query.strip():
            raise ValueError("Query must not be blank")
        return query  # Preserve the exact input separately from normalized input.


FiniteNumber = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class ParsedConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ingredients_available: list[str]
    ingredients_required: list[str]
    ingredients_excluded: list[str]
    dietary_restrictions: list[str]
    meal_type: str | None
    number_of_recipes: Annotated[int, Field(gt=0)] | None
    planning_days: Annotated[int, Field(gt=0)] | None
    max_calories: FiniteNumber | None
    min_protein_g: FiniteNumber | None
    max_cooking_time_minutes: FiniteNumber | None
    soft_preferences: list[str]


class ParsedIntent(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    dish_name: str | None = None
    dish_type: str | None = None
    meal_type: str | None = None
    cuisine: str | None = None
    intent: Literal[
        "recipe_search",
        "meal_planning",
        "recipe_comparison",
        "recipe_how_to",
        "recipe_question_answering",
        "unsupported_request",
        "unknown",
    ]
    status: Literal["ready", "needs_clarification", "unsupported"]
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    search_type: Literal["name_search", "constraint_search"] | None
    constraints: ParsedConstraints
    recipe_names: list[str]
    recipe_references: list[str]
    comparison_dimensions: list[str]
    question_type: str | None
    needs_clarification: bool
    clarification_question: str | None
    clarification_reasons: list[str]
    missing_fields: list[str]
    unsupported_reason: str | None
    normalization: dict[str, Any]
    strict_upper_bounds: list[dict[str, Any]]
    uncertain_questions: list[str]
    answers: dict[str, Any]


def validate_probabilities(payload, result):
    """Validate every probability shown by the UI, not just the winning label."""
    if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
        raise ValueError("Missing model answers")
    for name, question in payload["questions"].items():
        answer = result["answers"].get(name)
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise ValueError("Missing or invalid model answer")
        if question["type"] == "choice":
            probabilities = answer.get("probabilities")
            if not isinstance(probabilities, dict) or any(
                label not in question["criteria"] for label in probabilities
            ):
                raise ValueError("Invalid choice probabilities")
            values = probabilities.values()
        else:
            values = [answer.get("probability")]
        for value in values:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError("Invalid probability")


def constraint_rows(parsed):
    """Describe recognized facts separately from backend filter capabilities."""
    rows = []
    specs = {
        "ingredients_available": ("Available ingredients", "", "context", None),
        "ingredients_required": ("Required ingredients", "", "supported", "include_ingredients"),
        "ingredients_excluded": ("Excluded ingredients", "", "supported", "exclude_ingredients"),
        "dietary_restrictions": ("Dietary requirements", "", "unsupported", None),
        "meal_type": ("Meal type", "", "unsupported", None),
        "number_of_recipes": ("Requested recipe count", "recipes", "context", None),
        "planning_days": ("Planning duration", "days", "unsupported", None),
        "max_cooking_time_minutes": (
            "Maximum total time",
            "min",
            "supported",
            "max_total_time_minutes",
        ),
        "max_calories": ("Maximum calories", "kcal / serving", "supported", "max_calories"),
        "min_protein_g": ("Minimum protein", "g / serving", "unsupported", None),
        "soft_preferences": ("Soft preferences", "", "preference", None),
    }
    for key, (label, unit, support, target) in specs.items():
        value = parsed["constraints"][key]
        if value is None or value == []:
            continue
        normalization = parsed["normalization"].get(key, {})
        source = normalization.get("source", "recognized")
        rows.append(
            {
                "field": key,
                "label": label,
                "value": value,
                "unit": unit,
                "operator": "≤"
                if key.startswith("max_")
                else "≥"
                if key.startswith("min_")
                else "",
                "source": source,
                "support": support,
                "target_filter": target,
                "applied": False,
                "needs_confirmation": source == "system_default",
            }
        )
    for bound in parsed["strict_upper_bounds"]:
        rows.append(
            {
                "field": bound["field"],
                "label": "Strict upper bound",
                "value": bound["value"],
                "unit": "kcal / serving" if bound["field"] == "max_calories" else "min",
                "operator": "<",
                "source": "recognized",
                "support": "unsupported",
                "target_filter": None,
                "applied": False,
                "needs_confirmation": False,
            }
        )
    if parsed.get("ingredient_preferences"):
        rows.append(
            {
                "field": "ingredient_preferences",
                "label": "Preferred ingredients",
                "value": parsed["ingredient_preferences"],
                "unit": "",
                "operator": "",
                "source": "recognized",
                "support": "preference",
                "target_filter": None,
                "applied": False,
                "needs_confirmation": False,
            }
        )
    return rows


def parse_intent(request: IntentRequest):
    started = time.perf_counter()
    request_id = str(uuid4())
    query = request.query.strip()
    try:
        payload, ingredients, numbers = jev.prepare(query, [])
        candidates = schema.extend_request(payload, query, request.context.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_candidates", "message": str(exc)}
        ) from None
    key = get_settings().credential("JEV_API_KEY") or get_settings().credential(
        "AI_GATEWAY_API_KEY"
    )
    if not key:
        raise HTTPException(
            status_code=503,
            detail={"code": "missing_api_key", "message": "Jev is not configured on the server."},
        )
    if not PARSE_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail={"code": "intent_busy", "message": "Intent parsing is busy. Please retry."},
        )
    try:
        try:
            raw = jev.evaluate(payload, key, TIMEOUT_SECONDS)
        except ValueError as exc:
            message = str(exc).replace(key, "[REDACTED]")
            status = 504 if "timed out" in message.lower() else 502
            raise HTTPException(
                status_code=status,
                detail={
                    "code": "jev_request_failed",
                    "message": message,
                    "request_id": request_id,
                    "intent_parse_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            ) from None
        try:
            validate_probabilities(payload, raw)
            base = jev.interpret(payload, raw, ingredients, numbers, THRESHOLD)
            assembled = schema.assemble(base, raw, candidates, THRESHOLD, quick_minutes=30)
            parsed = ParsedIntent.model_validate(assembled).model_dump()
        except (ValueError, KeyError, TypeError, ValidationError):
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "invalid_model_output",
                    "message": "Jev returned an invalid parsing result. Please retry.",
                    "request_id": request_id,
                    "intent_parse_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            ) from None
    finally:
        PARSE_SLOTS.release()

    # Jev classifies dictionary/regex candidates; it does not generate search text.
    parsed["search_text"] = query
    from recipe_search.retrieval.query_builder import build_queries

    parsed["retrieval_queries"] = build_queries(parsed)
    route = (
        "supported"
        if parsed["intent"] == "recipe_search"
        else "unknown"
        if parsed["intent"] == "unknown"
        else "unsupported"
    )
    return {
        "request_id": request_id,
        "raw_query": request.query,
        "query": query,
        "usage": raw.get("usage"),
        **usage_metrics(raw.get("usage"), payload["model"]),
        "provider": "vercel_gateway",
        "corrections": [],
        "warnings": [
            "Jev evaluates dictionary/regex candidates. Missing ingredients may reflect limited candidate coverage, not absence of ingredient requirements.",
            "Dish name, dish type, meal type and cuisine extraction is not supported by this Jev adapter.",
            "Jev does not support specific/category classification or equivalent core-ingredient identification; its legacy mapping is unchanged.",
        ],
        "search_text_source": "original_query",
        "extraction_method": "candidate_classification",
        "model": payload["model"],
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "threshold": THRESHOLD,
        "intent_parse_ms": round((time.perf_counter() - started) * 1000, 2),
        "parsed": parsed,
        "constraint_rows": constraint_rows(parsed),
        "intent_scores": raw["answers"]["intent"]["probabilities"],
        "intent_descriptions": schema.INTENTS,
        "execution_support": route,
        "filters_applied": False,
        "context": request.context.model_dump(),
        "candidates": {
            "ingredients": ingredients,
            "numbers": numbers,
            "recipe_names": candidates["names"],
            "extra_numbers": candidates["numbers"],
        },
    }


@router.post("/intent/parse")
def api_parse_intent(request: IntentRequest):
    return parse_intent(request)
