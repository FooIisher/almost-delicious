"""Evidence for explicit total-time filters; never changes ranking scores."""

import math

OPERATORS = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
}
BUCKETS = {
    "less_30": [("lt", 30)],
    "30_60": [("gte", 30), ("lte", 60)],
    "60_120": [("gte", 60), ("lte", 120)],
    "120_180": [("gt", 120), ("lte", 180)],
    "more_180": [("gt", 180)],
}


def time_constraint_matches(recipe, settings):
    settings = settings.model_dump() if hasattr(settings, "model_dump") else settings
    bounds = [
        (c["operator"], c["value"])
        for c in settings.get("numeric_filters", [])
        if c["field"] == "total_time"
    ]
    if settings.get("max_total_time_minutes") is not None:
        bounds.append(("lte", settings["max_total_time_minutes"]))
    bounds.extend(BUCKETS.get(settings.get("cook_time"), []))
    value = recipe.get("total_time_minutes")
    valid = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )
    return [
        dict(
            field="total_time_minutes",
            operator=op,
            threshold=threshold,
            value=value if valid else None,
            unit="min",
            status=("met" if OPERATORS[op](value, threshold) else "not_met")
            if valid
            else "missing",
            scoring=False,
        )
        for op, threshold in dict.fromkeys(bounds)
    ]
