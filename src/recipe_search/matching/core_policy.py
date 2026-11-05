"""Evidence-based core protection; model flags alone never protect an ingredient."""

import re
from recipe_search.matching.ingredient_match import matches


def intrinsic_match(name, target):
    # Separately requested additions are not intrinsic to the named dish.
    identity = re.split(
        r"\b(?:with|containing|using|plus|served with)\b", target or "", maxsplit=1, flags=re.I
    )[0]
    return bool(identity.strip() and matches(name, identity))


def apply_core_policy(extraction, query=None):
    required = [i for i in extraction.ingredients if i.role == "required"]
    sole = len(required) == 1 and (
        extraction.required_expression is None or extraction.required_expression.op == "ingredient"
    )
    emphasized = []
    if query:
        # Stop at a new clause/requirement: "must have beef and finish in 15 min"
        # must not protect an unrelated ingredient mentioned later in the request.
        for span in re.findall(
            r"\b(?:must\s+(?:have|contain|include)|especially|insist on)\s+([^.!?;]+)", query, re.I
        ):
            emphasized.append(
                re.split(
                    r"\b(?:but|while|then|with|and\s+(?:it|the|finish|cook|must))\b",
                    span,
                    maxsplit=1,
                    flags=re.I,
                )[0]
            )
    reasons = {}
    target = extraction.dish_name or ""
    target_evidence = extraction.target_evidence.dish_name or ""
    for item in extraction.ingredients:
        reason = None
        if item.role == "required" and item.entity_type == "specific":
            if any(matches(item.name, span) for span in emphasized):
                reason = "explicit_emphasis"
            elif (
                intrinsic_match(item.name, target)
                and intrinsic_match(item.name, target_evidence)
                and (query is None or target_evidence.casefold() in query.casefold())
            ):
                reason = "dish_identity"
            elif sole:
                reason = "sole_required"
        item.core = reason is not None
        if reason:
            reasons[item.name] = reason
    object.__setattr__(extraction, "_core_reasons", reasons)
    return extraction
