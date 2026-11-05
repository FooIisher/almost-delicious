"""Explicit live evaluation against a running local server. Paid calls, no automatic retry.
Writes a fresh directory; never overwrites historical experiments. Use --case to limit scope.
"""

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from recipe_search.retrieval.query_builder import build_queries


def post(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=420) as response:
        return json.load(response)


def build(parsed):
    ingredients = parsed["ingredients"]

    def roles(role, kind):
        return [i["name"] for i in ingredients if i["role"] == role and i["entity_type"] == kind]

    q = build_queries(parsed, parsed)
    r = dict(
        query=q["bm25_query"],
        bm25_query=q["bm25_query"],
        vector_query=q["vector_query"],
        vector_scope_query=q["vector_scope_query"],
        vector_scope_weight=0.3,
        mode="hybrid",
        include_ingredients=roles("required", "specific"),
        exclude_ingredients=roles("excluded", "specific"),
        category_required=roles("required", "category"),
        category_excluded=roles("excluded", "category"),
        required_expression=parsed.get("required_expression"),
        dish_name_target=parsed.get("dish_name") or "",
        dish_type_target=parsed.get("dish_type") or "",
        cuisine_target=parsed.get("cuisine") or "",
        cuisine_role=parsed.get("cuisine_role"),
        meal_type_target=parsed.get("meal_type") or "",
        bm25_cuisine=parsed.get("cuisine") or "",
        bm25_meal_type=parsed.get("meal_type") or "",
        retrieval_strategy="text",
        numeric_filters=[
            {k: b[k] for k in ("field", "operator", "value", "basis")}
            for b in parsed["bounds"]
            if b["basis"] in ("not_applicable", "per_serving")
        ],
    )
    for role in ("available", "prefer", "avoid"):
        r["preference_" + role] = roles(role, "specific")
    r["preference_cuisine"] = [parsed["cuisine"]] if parsed.get("cuisine") else []
    r["preference_meal_type"] = [parsed["meal_type"]] if parsed.get("meal_type") else []
    return r


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument(
        "--model",
        choices=["deepseek-flash", "gpt41-mini", "gpt41-nano", "gpt6"],
        default="deepseek-flash",
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--case", action="append")
    parser.add_argument("--cases-file", type=Path, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline", help="Prior summary.json to display alongside this run")
    parser.add_argument("--cuisine-boost", type=float, default=6)
    parser.add_argument("--cuisine-weight", type=float, default=3)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.cases_file.read_text())
    cases = [c for c in cases if not args.case or c["id"] in args.case]
    records = []
    for case in cases:
        for run in range(1, args.runs + 1):
            row = dict(
                case=case,
                run=run,
                model=args.model,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            started = time.perf_counter()
            try:
                intent = post(
                    args.base_url + "/intent/parse/" + args.model, {"query": case["query"]}
                )
                row["intent"] = intent
                if intent.get("schema_version") != "recipe-extraction-v6":
                    raise RuntimeError(
                        "Restart backend with v6 extraction schema before this evaluation"
                    )
                row["status_matches_expected"] = (
                    intent["parsed"]["status"] == case["expected_status"]
                )
                if (
                    intent["parsed"]["status"] == "ready"
                    and intent["parsed"]["intent"] == "recipe_search"
                ):
                    settings = build(intent["parsed"]["extraction"])
                    settings.update(
                        bm25_cuisine_boost=args.cuisine_boost,
                        preference_weight_cuisine=args.cuisine_weight,
                    )
                    row["retrieval_settings"] = settings
                    retrieval = post(args.base_url + "/recipes/search", settings)
                    row["retrieval"] = retrieval
                    ids = retrieval["generation_candidate_ids"]
                    if ids:
                        row["generation"] = post(
                            args.base_url + "/content/generate/" + args.model,
                            dict(
                                query=case["query"],
                                intent_snapshot=intent,
                                retrieval_snapshot=settings,
                                recipe_ids=ids,
                                retrieval_trace={
                                    "bm25_fallback": retrieval.get("bm25_fallback"),
                                    "branch_filters": retrieval.get("branch_filters"),
                                    "generation_candidate_levels": retrieval.get(
                                        "generation_candidate_levels"
                                    ),
                                },
                            ),
                        )
            except urllib.error.HTTPError as error:
                row["error"] = json.loads(error.read())
                detail = row["error"].get("detail", {})
                if isinstance(detail, dict) and detail.get("task") == "content_generation":
                    row["generation"] = detail
            except Exception as error:
                row["error"] = str(error)
            row["wall_ms"] = round((time.perf_counter() - started) * 1000, 2)
            records.append(row)
            (output / f"{case['id']}-{run}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=2)
            )
    good = [r for r in records if "error" not in r]
    latency = [r["wall_ms"] for r in good]
    summary = dict(
        cuisine_boost=args.cuisine_boost,
        cuisine_weight=args.cuisine_weight,
        model=args.model,
        runs=len(records),
        successful=len(good),
        status_correct=sum(r.get("status_matches_expected", False) for r in records),
        wall_median_ms=statistics.median(latency) if latency else None,
        wall_p95_ms=percentile(latency, 0.95),
        generation_calls=sum(len(r.get("generation", {}).get("model_calls", [])) for r in records),
        known_input_tokens=sum(
            (r.get(s, {}).get("token_usage", {}).get("input_tokens") or 0)
            for r in records
            for s in ("intent", "generation")
        ),
        known_output_tokens=sum(
            (r.get(s, {}).get("token_usage", {}).get("output_tokens") or 0)
            for r in records
            for s in ("intent", "generation")
        ),
        note="Status agreement is not semantic accuracy. Review recorded recipes/conditions against each case annotation. Missing usage is unavailable, not proof of zero cost.",
    )
    summary["cost_estimates"] = [
        r.get(s, {}).get("cost_estimate")
        for r in records
        for s in ("intent", "generation")
        if r.get(s, {}).get("cost_estimate")
    ]
    if args.baseline:
        summary["baseline"] = json.loads(Path(args.baseline).read_text())
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("cost_estimates", "baseline")}, indent=2
        )
    )


if __name__ == "__main__":
    main()
