"""Build positive, editable retrieval text without reintroducing raw negative requests."""

import re
from recipe_search.matching.constraint_logic import normalized


def build_queries(parsed, extraction=None):
    e = extraction or parsed.get("extraction") or {}
    if hasattr(e, "model_dump"):
        e = e.model_dump()

    def get(key):
        return str(parsed.get(key) or e.get(key) or "").strip()

    ingredients = e.get("ingredients", [])

    def positive(text):
        # Delete original negative evidence only when it contains a complete negative
        # clause. A bare ingredient evidence is removed with its introducer below.
        for item in ingredients:
            if item.get("role") not in ("excluded", "avoid"):
                continue
            evidence = item.get("evidence", "")
            if re.search(r"\b(no|without|avoid|allergic|hate|dislike)\b", evidence, re.I):
                text = re.sub(re.escape(evidence), " ", text, flags=re.I)
        text = re.sub(
            r"\b(?:without|excluding|exclude|avoid|no(?![\w-])|allergic to|do not like|don.t like|hate)\s+.*?(?=\b(?:but with|with|and with|and prefer)\b|[,;.!?]|$)",
            " ",
            text,
            flags=re.I,
        )
        text = re.sub(r"\bbut\s+(?=with\b)", "", text, flags=re.I)
        return re.sub(r"\s+", " ", re.sub(r"\b(?:but|and)\s*$", "", text, flags=re.I)).strip(
            " ,;.!?"
        )

    name = get("dish_name")
    kind = get("dish_type")
    required = [
        i["name"]
        for i in ingredients
        if i.get("role") == "required" and i.get("entity_type") == "specific"
    ]

    def mandatory(node):
        if not node:
            return set()
        if node["op"] == "ingredient":
            return {normalized(node["ingredient"])}
        sets = [mandatory(c) for c in node["children"]]
        return set.union(*sets) if node["op"] == "AND" else set.intersection(*sets)

    if e.get("required_expression"):
        needed = mandatory(e["required_expression"])
        required = [x for x in required if normalized(x) in needed]
    description = positive(get("search_text") or get("search_description"))
    positive_ingredients = [
        i["name"] for i in ingredients if i.get("role") in ("required", "available", "prefer")
    ]
    flavors = list(
        dict.fromkeys(
            re.findall(
                r"\b(?:spicy|mild|smoky|sweet|savory|savoury|tangy|creamy|crispy)\b",
                description,
                re.I,
            )
        )
    )
    bm25 = positive(name or (" ".join(flavors + required + [kind]) if kind else description))
    if not bm25:
        bm25 = positive(
            " ".join(required + positive_ingredients + [kind, get("cuisine"), get("meal_type")])
        )
    vector = positive(name or description or bm25)
    if not name:
        for scope in (get("cuisine"), get("meal_type")):
            if scope:
                vector = re.sub(r"(?<!\w)" + re.escape(scope) + r"(?!\w)", " ", vector, flags=re.I)
        vector = " ".join(vector.split()).strip(" ,;.!?")
        if not vector:
            vector = positive(" ".join(positive_ingredients + [kind])) or bm25
    scope_text = description or positive(" ".join([get("cuisine"), get("meal_type"), vector]))
    for value in (get("cuisine"), get("meal_type")):
        if value and (" " + normalized(value) + " ") not in (" " + normalized(scope_text) + " "):
            scope_text += " " + value
    scope_text = scope_text.strip()
    warnings = []
    if normalized(scope_text) == normalized(vector) and vector:
        scope_text = ""
        warnings.append("Vector main and scope text are identical; scope weighting is skipped.")
    return dict(
        bm25_query=bm25,
        vector_query=vector,
        vector_scope_query=scope_text,
        source="Dish name"
        if name
        else "Positive flavor modifiers + Required ingredients + Dish type"
        if kind
        else "Positive description",
        warnings=warnings
        if bm25 and vector
        else warnings + ["Enter a positive retrieval query before retrieving."],
    )
