from recipe_search.settings import PACKAGE_ROOT
from recipe_search.matching.ingredient_match import matches
from recipe_search.matching.ingredient_sources import values as ingredient_values, evidence_sources
from recipe_search.matching.dish_match import dish_type_evidence
from recipe_search.matching.tag_expansion import tag_matches

"""Explainable reranking over the retained RRF candidate pool."""
import json
import math

RULES = json.loads((PACKAGE_ROOT / "config/preference_rules.json").read_text())


def rerank(rows, request):
    ceiling = ((request.bm25_boost + request.vector_boost) if request.mode == "hybrid" else 1) / (
        request.rrf_k + 1
    )
    groups = {
        name: getattr(request, "preference_" + name)
        for name in (
            "available",
            "prefer",
            "avoid",
            "cuisine",
            "meal_type",
            "dish_type",
            "healthy",
            "quick",
            "easy",
            "flavor",
        )
    }
    weights = {name: getattr(request, "preference_weight_" + name) for name in groups}
    positives = sum(weights[name] for name, values in groups.items() if name != "avoid" and values)
    for row in rows:
        source = row["hit"]["_source"]

        def values(field):
            value = source.get(field) or []
            return [str(x).casefold() for x in (value if isinstance(value, list) else [value])]

        tags = set(values("keywords") + values("recipecategory"))
        ingredients = ingredient_values(source)
        evidence = []
        score = 0.0
        for name, requested in groups.items():
            if not requested:
                continue
            ingredients = ingredient_values(
                source, preparation_only=name in ("available", "prefer")
            )
            matched = [
                x
                for x in requested
                if (
                    any(matches(x, ingredient) for ingredient in ingredients)
                    if name in ("available", "prefer", "avoid")
                    else x.casefold() in tags
                )
            ]
            checks = []
            if name in ("available", "prefer", "avoid"):
                checks = [
                    dict(
                        target=target,
                        evidence=[value for value in ingredients if matches(target, value)],
                        evidence_sources=evidence_sources(
                            source, [value for value in ingredients if matches(target, value)]
                        ),
                    )
                    for target in requested
                ]
                match_score = len(matched) / len(requested)
            elif name == "meal_type":
                details = [tag_matches("meal_types", x, tags) for x in requested]
                matched = [str(tag) for found, _ in details for tag, _ in found]
                match_score = sum(weight for _, weight in details) / len(requested)
            elif name == "dish_type":
                proofs = {
                    target: dish_type_evidence(target, source.get("name", ""), tags)
                    for target in requested
                }
                matched = [target for target, proof in proofs.items() if proof]
                checks = [dict(target=target, evidence=proof) for target, proof in proofs.items()]
                match_score = len(matched) / len(requested)
            elif name == "flavor":
                proofs = {
                    target: dish_type_evidence(target, source.get("name", ""), tags)
                    for target in requested
                }
                matched = [target for target, proof in proofs.items() if proof]
                checks = [dict(target=target, evidence=proof) for target, proof in proofs.items()]
                match_score = len(matched) / len(requested)
            elif name == "healthy":
                for rule in RULES["healthy"]:
                    value = source.get(rule["field"])
                    valid = (
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(value)
                        and value >= 0
                    )
                    passed = valid and (
                        value >= rule["threshold"]
                        if rule["operator"] == "gte"
                        else value <= rule["threshold"]
                    )
                    checks.append(
                        {
                            **rule,
                            "value": value if valid else None,
                            "status": "met" if passed else "not_met" if valid else "missing",
                        }
                    )
                matched = [
                    f"{x['field']}: {x['value']} {x['unit']}"
                    for x in checks
                    if x["status"] == "met"
                ]
                match_score = len(matched) / len(RULES["healthy"])
            elif name == "quick":
                value = source.get("total_time_minutes")
                valid = (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    and value > 0
                )
                matched = (
                    [f"total time: {value} min"]
                    if valid and value <= RULES["quick_minutes"]
                    else []
                )
                checks = [
                    dict(
                        field="total_time_minutes",
                        value=value if valid else None,
                        threshold=RULES["quick_minutes"],
                        unit="minutes",
                        status="met" if matched else "not_met" if valid else "missing",
                    )
                ]
                match_score = float(bool(matched))
            elif name == "easy":
                matched = ["easy"] if "easy" in tags else []
                match_score = float(bool(matched))
            else:
                match_score = len(matched) / len(requested)
            contribution = (
                -weights[name] * match_score
                if name == "avoid"
                else weights[name] * match_score / positives
                if positives
                else 0.0
            )
            score += contribution
            evidence.append(
                dict(
                    group=name,
                    requested=requested,
                    matched=matched,
                    weight=weights[name],
                    match_score=match_score,
                    checks=checks,
                    contribution=contribution,
                    final_contribution=request.preference_lambda * contribution,
                )
            )
        row.update(
            rrf_rank=row["rank"],
            normalized_rrf=row["rrf_score"] / ceiling,
            preference_score=score,
            preference_evidence=evidence,
        )
        rating = source.get("aggregatedrating")
        valid_rating = (
            isinstance(rating, (int, float))
            and not isinstance(rating, bool)
            and math.isfinite(rating)
        )
        rating_factor = min(rating, 5) / 5 if valid_rating and rating >= 3 else 0.0
        row["rating_factor"] = rating_factor
        row["rating_bonus"] = request.rating_boost * rating_factor
        row["rating_value"] = rating if valid_rating else None
        row["final_score"] = (
            row["normalized_rrf"] + request.preference_lambda * score + row["rating_bonus"]
        )
    rows.sort(key=lambda row: (-row["final_score"], row["rrf_rank"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows
