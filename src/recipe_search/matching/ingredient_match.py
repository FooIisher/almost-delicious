from recipe_search.settings import PACKAGE_ROOT

"""Conservative, shared positive ingredient matching; nonmatches need semantic review."""
import html
import json
import re
from functools import lru_cache
from recipe_search.matching.wordforms import candidates

RULES = json.loads((PACKAGE_ROOT / "config/ingredient_compounds.json").read_text())


def norm(value):
    return " ".join(re.findall(r"[^\W_]+", html.unescape(str(value)).casefold()))


def matches(target, ingredient):
    target = norm(target)
    text = norm(ingredient)
    if not target or not text:
        return False
    rule = next((RULES[v] for v in sorted(candidates(target)) if v in RULES), {})
    forms = {norm(v) for v in candidates(target)} | {norm(v) for v in rule.get("include", [])}
    if any((" " + norm(v) + " ") in (" " + text + " ") for v in rule.get("exclude", [])):
        return False
    for form in forms:
        # Negation is scoped to the target phrase, not unrelated modifiers.
        if re.search(
            r"\b(?:no|without|free of) "
            + re.escape(form)
            + r"\b|\b"
            + re.escape(form)
            + r" free\b",
            text,
        ):
            continue
        if (" " + form + " ") in (" " + text + " "):
            return True
    return False


@lru_cache(maxsize=512)
def expand(target, field="ingredients"):
    data = json.loads((PACKAGE_ROOT / "config/bm25_vocabulary.json").read_text())
    vocabulary = (
        data["fields"].get("ingredients_raw", data["fields"]["ingredients"])
        if field == "ingredients"
        else data["fields"].get(field, [])
    )
    return sorted(v for v in vocabulary if matches(target, v))


def ingredient_clause(target, excluded=False):
    fields = (
        ("ingredients", "extract_ingredients")
        if excluded
        else ("ingredients", "extract_ingredients_firm")
    )
    clauses = [
        {"terms": {field: forms}}
        for field in fields
        if (
            forms := expand(
                target, "extract_ingredients" if field == "extract_ingredients_firm" else field
            )
        )
    ]
    return (
        {"bool": {"should": clauses, "minimum_should_match": 1}} if clauses else {"match_none": {}}
    )
