"""Presentation-only images: original photo, then a similar recipe's photo, then a dish-form icon.

Source recipe data is never modified. The similar-recipe mapping is built offline by
scripts/build_image_fallback.py and read from a read-only SQLite file.
"""
from __future__ import annotations
import os
from recipe_text import clean_recipe
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

BORROWED_DB = Path(os.environ.get("RECIPE_IMAGE_FALLBACK_DB", Path(os.environ.get("DATA_DIR", Path.home()/".local/share/almost-delicious")) / "derived/image_fallback_v2.sqlite"))
BORROWED_LABEL = "Similar recipe photo"
_local = threading.local()

FALLBACK_IMAGE_BASE_URL = "/assets/recipe-icons"
FALLBACK_VARIANT_COUNT = 1
# Specific forms precede broad baked/dessert tags at each evidence tier.
FORMS = (
    ("stirfry", r"\bstir[- ]?fr(?:y|ied|ies)\b|\bwok\b"),
    ("salad", r"\bsalads?\b"),
    ("soup", r"\b(?:soups?|stews?|chowder|chili|chilli|bisque|broth)\b"),
    ("pasta", r"\b(?:pasta|spaghetti|fettuccine|lasagn[ae]|penne|noodles?|mac|macaroni)\b"),
    ("rice", r"\b(?:rice|risotto|pilaf|paella)\b"),
    ("sandwich", r"\b(?:sandwich(?:es)?|burgers?|hamburgers?|wraps?|toast)\b"),
    ("drink", r"\b(?:smoothies?|shakes?|juice|punch|lemonade|drinks?|beverages?|cocktails?)\b"),
    ("breakfast", r"\b(?:breakfast|omelet(?:te)?s?|pancakes?|waffles?|scrambled eggs?)\b"),
    ("dessert", r"\b(?:baked|baking|cakes?|cheesecakes?|cookies?|brownies?|pies?|pudding|ice[- ]cream|desserts?|muffins?|bread)\b"),
)
LABELS = {"stirfry":"Stir fry", "soup":"Soup / stew", "salad":"Salad", "pasta":"Pasta / noodles", "rice":"Rice", "dessert":"Baked / dessert", "sandwich":"Sandwich / burger", "drink":"Drink / smoothie", "breakfast":"Breakfast", "default":"Recipe"}

def _values(value):
    if isinstance(value,str):return [value]
    if isinstance(value,(list,tuple)):return [v for v in value if isinstance(v,str)]
    return []

def choose_fallback_category(recipe: dict[str, Any]) -> str:
    tiers = (_values(recipe.get("name")), _values(recipe.get("keywords")) + _values(recipe.get("recipecategory")), _values(recipe.get("ingredients")))
    for values in tiers:
        text=" ".join(values).casefold()
        for form,pattern in FORMS:
            if re.search(pattern,text):return form
    return "default"

def choose_variant(recipe: dict[str, Any], category: str | None = None) -> int:
    """One clearly symbolic icon per form; retained for caller compatibility."""
    return 1

def choose_fallback_image(recipe: dict[str, Any]) -> tuple[str,str]:
    category=choose_fallback_category(recipe)
    return f"{FALLBACK_IMAGE_BASE_URL}/{category}.svg", f"fallback:{category}:1"

def _connection():
    """One read-only connection per thread; None when the mapping file is absent."""
    if not hasattr(_local, "con"):
        _local.con = None
        if BORROWED_DB.is_file():
            try:
                _local.con = sqlite3.connect(f"file:{BORROWED_DB}?mode=ro&immutable=1", uri=True, check_same_thread=False)
            except sqlite3.Error:
                _local.con = None
    return _local.con

def borrowed_image(recipe: dict[str, Any]) -> dict[str, Any] | None:
    """Photo of a similar recipe that has one (offline name/ingredient mapping)."""
    rid = recipe.get("recipeid", recipe.get("recipe_id"))
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    con = _connection()
    if con is None:
        return None
    try:
        row = con.execute("SELECT image_url, level, score, image_recipeid, image_name FROM fallback WHERE recipeid=?", (rid,)).fetchone()
    except sqlite3.Error:
        return None
    if not row or not str(row[0]).startswith(("https://", "http://")):
        return None
    return dict(url=row[0], level=row[1], score=row[2], recipe_id=row[3], name=row[4])

def choose_display_image(recipe: dict[str, Any]) -> tuple[str,str]:
    for url in _values(recipe.get("image_urls")):
        if url.strip().lower().startswith(("https://","http://")):return url.strip(),"original"
    borrowed = borrowed_image(recipe)
    if borrowed:
        return borrowed["url"], f"borrowed:{borrowed['level']}"
    return choose_fallback_image(recipe)

def enrich_recipe_for_display(recipe: dict[str, Any]) -> dict[str, Any]:
    recipe=clean_recipe(recipe)
    image,source=choose_display_image(recipe)
    fallback,_=choose_fallback_image(recipe)
    category=choose_fallback_category(recipe)
    borrowed = borrowed_image(recipe) if source.startswith("borrowed:") else None
    return {**recipe,"extract_ingredients":[v for v in _values(recipe.get("extract_ingredients")) if v.strip()],
            "display_image_url":image,"fallback_image_url":fallback,"image_source":source,
            "fallback_category":category,"fallback_label":LABELS[category],"has_original_image":source=="original",
            "borrowed_image":({"recipe_id":borrowed["recipe_id"],"name":borrowed["name"],"level":borrowed["level"],"score":borrowed["score"],"label":BORROWED_LABEL} if borrowed else None)}

def dedupe_borrowed_images(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Within one result page a borrowed photo is shown once; later repeats fall back to the icon."""
    seen: set[str] = set()
    for item in results:
        if str(item.get("image_source", "")).startswith("borrowed:"):
            url = item.get("display_image_url")
            if url in seen:
                item.update(display_image_url=item.get("fallback_image_url"), image_source=f"fallback:{item.get('fallback_category','default')}:1", borrowed_image=None)
            else:
                seen.add(url)
    return results
