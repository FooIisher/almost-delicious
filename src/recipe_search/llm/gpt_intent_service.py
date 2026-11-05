from recipe_search.retrieval.query_builder import build_queries
from recipe_search.settings import get_settings

"""Direct OpenAI and DeepSeek adapters for the intent preview UI."""
import hashlib
import json
import logging
import os
import socket
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from recipe_search.llm.extraction_schema import (
    ENDPOINT,
    MODEL,
    PROMPT,
    SCHEMA_VERSION,
    TARGET_FIELDS,
    Extraction,
    parse_response,
)
from recipe_search.llm.intent_service import PARSE_SLOTS, IntentRequest, router
from recipe_search.llm.intent_usage import usage_metrics
from recipe_search.matching.constraint_logic import RequiredExpression, normalized, references

DIAGNOSTICS_DIR = get_settings().output_dir / "intent-failures"
logger = logging.getLogger("uvicorn.error")


def save_failure(record, key):
    """Never persist request headers or credentials, even if echoed in model text."""
    payload = json.dumps(record, ensure_ascii=False, indent=2, default=str)
    if key:
        payload = payload.replace(key, "[REDACTED]")
    try:
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        path = DIAGNOSTICS_DIR / (record["diagnostic_id"] + ".json")
        with path.open("x", encoding="utf-8") as output:
            os.chmod(path, 0o600)
            output.write(payload + "\n")
        return True
    except OSError:
        return False


def present(p, query, context, elapsed, raw):
    rows = []

    def row(field, label, value, support="unsupported", unit="", operator="", evidence=None):
        rows.append(
            dict(
                field=field,
                label=label,
                value=value,
                support=support,
                unit=unit,
                operator=operator,
                evidence=evidence,
                source="recognized",
                applied=False,
                needs_confirmation=False,
                target_filter=None,
            )
        )

    for x in p.ingredients:
        row(
            "ingredient_" + x.role,
            {
                "available": "Available ingredient",
                "required": "Required ingredient",
                "excluded": "Excluded ingredient",
                "prefer": "Preferred ingredient",
                "avoid": "Ingredient to avoid",
            }[x.role],
            [x.name],
            {
                "available": "context",
                "required": "supported",
                "excluded": "supported",
                "prefer": "preference",
                "avoid": "preference",
            }[x.role],
            evidence=x.evidence,
        )
        rows[-1].update(
            entity_type=x.entity_type,
            role=x.role,
            core=x.core,
            core_reason=getattr(p, "_core_reasons", {}).get(x.name),
        )
        if x.entity_type == "category":
            rows[-1].update(
                support="unsupported",
                execution_status="not_applied",
                execution_reason="Category constraints are not applied to filtering or ranking.",
            )
            if x.role in ("required", "available", "prefer"):
                rows[-1].update(
                    support="preference",
                    execution_status="bm25_boost_only",
                    execution_reason="Eligible for a BM25 keywords bonus only; not a hard filter or semantic validation.",
                )
    for x in p.bounds:
        row(
            x.field,
            {"total_time": "Total time", "calories": "Calories", "protein": "Protein"}[x.field],
            x.value,
            # Nutrition basis is not yet represented structurally; do not imply filter compatibility.
            "supported" if x.field == "total_time" or x.basis == "per_serving" else "unsupported",
            x.unit,
            {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "eq": "="}[x.operator],
            x.evidence,
        )
        rows[-1].update(basis=x.basis)
    if p.dietary_restrictions:
        row("diet", "Dietary requirements", p.dietary_restrictions)
    if p.soft_preferences:
        row("preferences", "Soft preferences", p.soft_preferences, "preference")
    questions = p.clarification_questions
    supported = p.intent == "recipe_search"
    parsed = dict(
        intent=p.intent,
        status="needs_clarification" if questions else "ready" if supported else "unsupported",
        **{field: getattr(p, field) for field in TARGET_FIELDS},
        target_evidence=p.target_evidence.model_dump(),
        confidence=None,
        search_type=None,
        search_text=p.search_text,
        clarification_question=" ".join(questions) or None,
        clarification_reasons=[],
        unsupported_reason=None,
        recipe_names=[],
        recipe_references=[],
        comparison_dimensions=[],
        question_type=None,
        missing_fields=[],
        uncertain_questions=[],
        extraction=p.model_dump(),
    )
    if parsed["status"] == "ready":
        parsed["retrieval_queries"] = build_queries(parsed, p)
    return dict(
        request_id=str(uuid4()),
        raw_query=query,
        model=raw.get("model", MODEL),
        provider="openai_direct",
        prompt_version=hashlib.sha256(PROMPT.encode()).hexdigest()[:12],
        schema_version=SCHEMA_VERSION,
        intent_parse_ms=elapsed,
        parsed=parsed,
        constraint_rows=rows,
        intent_scores={},
        threshold=None,
        filters_applied=False,
        execution_support="supported" if supported else "unsupported",
        context=context,
        corrections=[x.model_dump() for x in p.corrections],
        usage=raw.get("usage"),
    )


def normalize_approximate_time(extraction):
    """Canonicalize model-recognized approximate minute bounds to ±25%."""
    import re

    from recipe_search.llm.extraction_schema import Bound

    bounds = []
    seen = set()
    for bound in extraction.bounds:
        match = (
            re.search(
                r"\b(?:around|about|approximately|roughly)\s+(\d+(?:\.\d+)?)\s*(?:minutes?|mins?)\b",
                bound.evidence,
                re.I,
            )
            if bound.field == "total_time"
            else None
        )
        if not match:
            bounds.append(bound)
            continue
        key = bound.evidence.casefold().strip()
        if key in seen:
            continue
        seen.add(key)
        center = float(match.group(1))
        for operator, factor in [("gte", 0.75), ("lte", 1.25)]:
            bounds.append(
                Bound(
                    field="total_time",
                    operator=operator,
                    value=round(center * factor, 6),
                    unit="minutes",
                    basis="not_applicable",
                    evidence=bound.evidence,
                )
            )
    return extraction.model_copy(update={"bounds": bounds})


def ingredient_conflict_questions(extraction):
    """Catch exact-name hard conflicts, never infer category membership."""

    def canonical(item):
        name = " ".join(item.name.casefold().split())
        return "vegetable" if item.entity_type == "category" and name == "vegetables" else name

    required = {canonical(item) for item in extraction.ingredients if item.role == "required"}
    excluded = {canonical(item) for item in extraction.ingredients if item.role == "excluded"}
    questions = list(extraction.clarification_questions)
    seen = {" ".join(question.casefold().split()) for question in questions}
    conflicting = (required & excluded) - {""}
    for name in sorted(conflicting):
        question = (
            f"You asked to include {name} and also exclude it. Should it be included or excluded?"
        )
        key = " ".join(question.casefold().split())
        if key not in seen:
            questions.append(question)
            seen.add(key)
    for field in ("total_time", "calories", "protein"):
        bounds = [
            b
            for b in extraction.bounds
            if b.field == field and (field == "total_time" or b.basis == "per_serving")
        ]
        low = max(
            [(b.value, b.operator == "gt") for b in bounds if b.operator in ("gt", "gte", "eq")],
            default=None,
        )
        uppers = [
            (b.value, b.operator == "lt") for b in bounds if b.operator in ("lt", "lte", "eq")
        ]
        high = min(uppers, key=lambda b: (b[0], not b[1])) if uppers else None
        if low and high and (low[0] > high[0] or low[0] == high[0] and (low[1] or high[1])):
            question = f"The {field.replace('_', ' ')} limits conflict. Which range should apply?"
            if question not in questions:
                questions.append(question)
    return questions


OPENAI_MODELS = {"gpt6": MODEL, "gpt41-nano": "gpt-4.1-nano", "gpt41-mini": "gpt-4.1-mini"}
DEEPSEEK_ENDPOINT = get_settings().deepseek_endpoint
DEEPSEEK_FORMAT_INSTRUCTION = "Return a JSON object conforming to this JSON Schema: "


@router.post("/intent/parse/{model_key}")
def parse_gpt6(
    request: IntentRequest,
    model_key: Literal["gpt6", "gpt41-nano", "gpt41-mini", "deepseek-flash"] = "gpt6",
):
    deepseek = model_key == "deepseek-flash"
    selected_model = model_key if deepseek else OPENAI_MODELS[model_key]
    provider_name = "DeepSeek" if deepseek else "OpenAI"
    provider = "deepseek_direct" if deepseek else "openai_direct"
    key_name = "DEEPSEEK_API_KEY" if deepseek else "OPENAI_API_KEY"
    key = get_settings().credential(key_name)
    if not key:
        raise HTTPException(
            503,
            detail={
                "code": "missing_api_key",
                "message": f"Set {key_name} in the server terminal and restart the server.",
            },
        )
    if not PARSE_SLOTS.acquire(blocking=False):
        raise HTTPException(
            503, detail={"code": "intent_busy", "message": "Intent parsing is busy. Please retry."}
        )
    started = time.perf_counter()
    raw = None
    response_text = None
    stage = "response_json"
    issues = []
    try:
        body = dict(
            model=selected_model,
            store=False,
            max_output_tokens=3500,
            instructions=PROMPT,
            input=request.query,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "recipe_intent",
                    "strict": True,
                    "schema": Extraction.model_json_schema(),
                }
            },
        )
        if model_key == "gpt6":
            body["reasoning"] = {"effort": "low"}
        if deepseek:
            body = dict(
                model=selected_model,
                max_tokens=3500,
                stream=False,
                thinking={"type": "disabled"},
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": PROMPT},
                    {
                        "role": "system",
                        "content": DEEPSEEK_FORMAT_INSTRUCTION
                        + json.dumps(Extraction.model_json_schema()),
                    },
                    {"role": "user", "content": request.query},
                ],
            )
        req = urllib.request.Request(
            DEEPSEEK_ENDPOINT if deepseek else ENDPOINT,
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            response_text = response.read().decode("utf-8")
        raw = json.loads(response_text)
        stage = "structured_output"
        if not isinstance(raw, dict):
            raise ValueError("Expected a response object")
        if deepseek:
            choices = raw.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("DeepSeek returned no choices")
            choice = choices[0]
            if choice.get("finish_reason") != "stop":
                raise ValueError(
                    "DeepSeek output did not finish normally: " + str(choice.get("finish_reason"))
                )
            p = Extraction.model_validate_json(choice["message"]["content"])
        else:
            p = parse_response(raw)
        issues = []
        from recipe_search.matching.core_policy import apply_core_policy

        apply_core_policy(p, request.query)
        required_ingredients = [i for i in p.ingredients if i.role == "required"]

        # A single requirement has only one possible grouping. Repair a missing
        # tree without guessing AND/OR semantics for multiple requirements.
        if (
            "required_expression" in p.model_fields_set
            and p.required_expression is None
            and len({normalized(i.name) for i in required_ingredients}) == 1
        ):
            p.required_expression = RequiredExpression(
                op="ingredient", ingredient=required_ingredients[0].name, children=[]
            )
        if "required_expression" in p.model_fields_set:
            required_names = {normalized(i.name) for i in p.ingredients if i.role == "required"}
            used = {normalized(n) for n in references(p.required_expression)}
            if required_names != used:
                issues.append(
                    dict(
                        field="required_expression",
                        value=None,
                        reason="Required logic must reference every required ingredient; do not silently omit a condition.",
                    )
                )

        def evidence_issue(field, value, message):
            if value is not None and (
                not value or value.casefold() not in request.query.casefold()
            ):
                issues.append(
                    dict(
                        field=field,
                        value=value,
                        reason=message
                        + ": evidence must be a continuous substring of the original query (case-insensitive).",
                    )
                )

        for field, evidence in p.target_evidence.model_dump().items():
            evidence_issue(f"target_evidence.{field}", evidence, "Invalid target evidence")
        for group in ("ingredients", "bounds"):
            for index, x in enumerate(getattr(p, group)):
                evidence_issue(f"{group}.{index}.evidence", x.evidence, "Invalid evidence")
        for index, x in enumerate(p.corrections):
            evidence_issue(
                f"corrections.{index}.original", x.original, "Invalid correction evidence"
            )
        for index, x in enumerate(p.bounds):
            if (x.field == "total_time") != (x.basis == "not_applicable"):
                issues.append(
                    dict(
                        field=f"bounds.{index}.basis",
                        value=x.basis,
                        reason="Time requires not_applicable basis; nutrition requires a nutrition basis.",
                    )
                )
            expected = {"total_time": "minutes", "calories": "kcal", "protein": "g"}[x.field]
            if x.unit != expected:
                issues.append(
                    dict(
                        field=f"bounds.{index}.unit",
                        value=x.unit,
                        reason=f"Expected unit: {expected}",
                    )
                )
        if issues:
            stage = issues[0]["field"]
            raise ValueError("; ".join(x["field"] + ": " + x["reason"] for x in issues))
        p = normalize_approximate_time(p)
        p = p.model_copy(update={"clarification_questions": ingredient_conflict_questions(p)})
        stage = "presentation"
        result = present(
            p,
            request.query,
            {"recipes": [], "selected_recipe_id": None},
            round((time.perf_counter() - started) * 1000, 2),
            raw,
        )
        result["requested_model"] = selected_model
        result["model"] = raw.get("model") or selected_model
        result["provider"] = provider
        result.update(usage_metrics(raw.get("usage"), result["model"], raw.get("service_tier")))
        result["output_mode"] = "json_object" if deepseek else "json_schema"
        if deepseek:
            result["thinking_mode"] = "disabled"
            result["format_instruction_version"] = hashlib.sha256(
                body["messages"][1]["content"].encode()
            ).hexdigest()[:12]
        return result
    except urllib.error.HTTPError as e:
        try:
            code = json.loads(e.read()).get("error", {}).get("code")
        except (ValueError, AttributeError):
            code = None
        message = (
            f"{provider_name} API credits are exhausted. Check API billing."
            if e.code == 402 or code in ("credit_balance_exhausted", "insufficient_quota")
            else f"{provider_name} rejected the API key."
            if e.code == 401
            else f"{provider_name} rate limit reached. Please retry later."
            if e.code == 429
            else f"{provider_name} request failed. Check model access and server configuration."
        )
        raise HTTPException(
            502,
            detail={
                "code": "deepseek_request_failed" if deepseek else "openai_request_failed",
                "message": message,
            },
        ) from None
    except (TimeoutError, socket.timeout):
        raise HTTPException(
            504,
            detail={
                "code": "intent_timeout",
                "message": f"{provider_name} intent parsing timed out.",
            },
        ) from None
    except urllib.error.URLError:
        raise HTTPException(
            502,
            detail={"code": "connection_failed", "message": f"Cannot connect to {provider_name}."},
        ) from None
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        if isinstance(exc, ValidationError):
            issues = [
                dict(
                    field=".".join(map(str, e["loc"])) or "structured_output",
                    reason=e["msg"],
                    value=e.get("input"),
                )
                for e in exc.errors(include_url=False, include_context=False)
            ]
        if not issues:
            issues = [dict(field=stage, reason=str(exc), value=None)]
        model_text = ""
        if deepseek and isinstance(raw, dict):
            choices = raw.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    model_text = message["content"]
        if isinstance(raw, dict) and isinstance(raw.get("output"), list):
            for item in raw["output"]:
                if not isinstance(item, dict) or not isinstance(item.get("content"), list):
                    continue
                for part in item["content"]:
                    if isinstance(part, dict):
                        value = part.get("text") or part.get("refusal")
                        if isinstance(value, str):
                            model_text += value
        try:
            model_output = json.loads(model_text)
        except ValueError:
            model_output = model_text or response_text
        diagnostic_id = str(uuid4())
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        # Format before logging so credentials echoed inside invalid model data
        # cannot leak through an unsanitized exception message.
        error_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if key:
            error_trace = error_trace.replace(key, "[REDACTED]")
        logger.error(
            "Intent validation failed: model=%s stage=%s diagnostic_id=%s\n%s",
            selected_model,
            stage,
            diagnostic_id,
            error_trace,
        )
        saved = save_failure(
            {
                "diagnostic_id": diagnostic_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "query": request.query,
                "requested_model": selected_model,
                "provider": provider,
                "schema_version": SCHEMA_VERSION,
                "prompt_version": hashlib.sha256(PROMPT.encode()).hexdigest()[:12],
                "intent_parse_ms": elapsed,
                "validation_stage": stage,
                "exception_type": type(exc).__name__,
                "validation_error": str(exc),
                "validation_errors": issues,
                "raw_response": raw,
                "raw_response_text": response_text if raw is None else None,
            },
            key,
        )
        if not saved:
            logger.warning("Could not save intent diagnostic: diagnostic_id=%s", diagnostic_id)
        detail = dict(
            code="invalid_model_output",
            status="validation_failed",
            message="Model output failed validation. It is shown for review only; no conditions were applied.",
            diagnostic_id=diagnostic_id,
            request_id=diagnostic_id,
            diagnostic_saved=saved,
            raw_query=request.query,
            requested_model=selected_model,
            model=raw.get("model", selected_model) if isinstance(raw, dict) else selected_model,
            validation_stage=stage,
            intent_parse_ms=elapsed,
            validation_errors=issues,
            model_output=model_output,
            filters_applied=False,
            execution_support="blocked",
            usage=raw.get("usage") if isinstance(raw, dict) else None,
        )
        detail.update(
            usage_metrics(
                detail["usage"],
                detail["model"],
                raw.get("service_tier") if isinstance(raw, dict) else None,
            )
        )
        # Apply the same credential redaction to the browser response as to disk/logs.
        detail = json.loads(json.dumps(detail, default=str).replace(key, "[REDACTED]"))
        raise HTTPException(502, detail=detail) from None
    finally:
        PARSE_SLOTS.release()
