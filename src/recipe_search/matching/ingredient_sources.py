"""Ingredient facts retain their persisted field; extraction is never recipe rewriting."""

from recipe_search.matching.ingredient_match import norm

FIELDS = ("ingredients", "extract_ingredients")


def entries(recipe):
    return [
        dict(field=field, value=value)
        for field in FIELDS
        for value in (
            recipe.get(field)
            if isinstance(recipe.get(field), list)
            else [recipe[field]]
            if isinstance(recipe.get(field), str)
            else []
        )
        if isinstance(value, str) and value.strip()
    ]


def values(recipe, preparation_only=False):
    result = []
    seen = set()
    for entry in entries(recipe):
        if (
            preparation_only
            and entry["field"] == "extract_ingredients"
            and usage_for(recipe, entry["value"]) != "preparation"
        ):
            continue
        key = norm(entry["value"])
        if key not in seen:
            seen.add(key)
            result.append(entry["value"])
    return result


def evidence_sources(recipe, evidence):
    import html

    def key(value):
        return " ".join(html.unescape(str(value)).casefold().split())

    requested = {key(value) for value in evidence}
    return [
        {
            **entry,
            **(
                {"usage": usage_for(recipe, entry["value"])}
                if entry["field"] == "extract_ingredients"
                else {}
            ),
        }
        for entry in entries(recipe)
        if key(entry["value"]) in requested
    ]


def classify_usage(text, hedged=False, ingredient=None):
    """Conservative sentence-level provenance; unknown never proves required."""
    import re

    if ingredient:
        from recipe_search.matching.ingredient_match import matches

        parts = re.split(
            r"[.;]|\band\s+(?=(?:serve|garnish|add|stir|mix|cook|pour|toss)\b)|\bthen\s+",
            str(text),
            flags=re.I,
        )
        relevant = [part for part in parts if matches(ingredient, part)]
        uses = [classify_usage(part, hedged) for part in relevant]
        if "preparation" in uses:
            return "preparation"
        if uses and all(use == "serving_optional" for use in uses):
            return "serving_optional"
        return "unknown"
    if re.search(
        r"\b(?:serve(?:d)?\s+(?:with|alongside)|garnish|optional|optionally|if using|variation|substitute|instead of)\b",
        str(text),
        re.I,
    ):
        return "serving_optional"
    if hedged or re.search(r"\b(?:do not|don't|omit|skip|avoid)\b", str(text), re.I):
        return "unknown"
    if re.search(
        r"\b(?:add|stir|mix|cook|saute|sauté|fry|boil|simmer|bake|roast|combine|blend|place|put|heat|whisk|pour|season|toss|brown|marinate|fold)\b",
        str(text),
        re.I,
    ):
        return "preparation"
    return "unknown"


def usage_for(recipe, ingredient):
    records = [
        item
        for item in recipe.get("extract_evidence", [])
        if isinstance(item, dict) and norm(item.get("ingredient", "")) == norm(ingredient)
    ]
    uses = [
        item.get("usage")
        or classify_usage(item.get("text", ""), item.get("hedged", False), ingredient)
        for item in records
    ]
    if any(norm(ingredient) == norm(value) for value in recipe.get("extract_ingredients_firm", [])):
        uses.append("preparation")
    if "preparation" in uses:
        return "preparation"
    if uses and all(value == "serving_optional" for value in uses):
        return "serving_optional"
    return "unknown"


def usage_records(recipe):
    records = []
    for value in recipe.get("extract_ingredients", []):
        usage = usage_for(recipe, value)
        record = dict(ingredient=value, usage=usage)
        if usage == "unknown":
            record["context"] = [
                item["text"]
                for item in recipe.get("extract_evidence", [])
                if isinstance(item, dict)
                and norm(item.get("ingredient", "")) == norm(value)
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            ]
        records.append(record)
    return records
