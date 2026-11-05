"""Display-layer fallback image selection for recipe search results.

This module deliberately does not write to Elasticsearch.  It enriches only
the recipes returned by a request, keeping retrieval and source data intact.
"""

from __future__ import annotations

import hashlib
from typing import Any

FALLBACK_IMAGE_BASE_URL = "/assets/recipe-images"
FALLBACK_VARIANT_COUNT = 6
# Soup has an expanded visual set; all other categories retain six variants.
# Keeping selection deterministic gives a recipe a stable visual identity while
# spreading result cards across the available variants.
FALLBACK_VARIANT_COUNTS = {"soup": 12}

RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Sushi must precede rice: most sushi recipes also contain rice, but their
    # presentation fallback should remain recognisably sushi or maki.
    ("sushi", ("sushi", "maki", "nigiri", "sashimi", "temaki", "uramaki")),
    # Beef also precedes rice and chicken because recipes can contain either
    # rice or chicken broth while still being principally a beef dish.
    ("beef", ("beef",)),
    ("chicken", ("chicken",)),
    ("pasta", ("pasta", "spaghetti", "fettuccine", "lasagna", "penne", "noodle")),
    ("rice", ("rice", "risotto", "pilaf", "paella")),
    ("dessert", ("cake", "dessert", "chocolate", "cookie", "brownie", "cheesecake")),
    ("salad", ("salad",)),
    ("soup", ("soup", "stew", "chowder", "broth")),
)


def recipe_text(recipe: dict[str, Any]) -> str:
    """Build the small, presentation-only text signal used by fallback rules."""
    values = [
        recipe.get("name", ""),
        recipe.get("recipecategory", ""),
        *(recipe.get("ingredients") or []),
        *(recipe.get("keywords") or []),
    ]
    return " ".join(str(value) for value in values if value).lower()


def choose_fallback_category(recipe: dict[str, Any]) -> str:
    text = recipe_text(recipe)
    for category, terms in RULES:
        if any(term in text for term in terms):
            return category
    return "default"


def choose_variant(recipe: dict[str, Any], category: str | None = None) -> int:
    """Use a stable recipe id hash so the same result keeps the same image."""
    key = str(recipe.get("recipeid") or recipe.get("name") or "default")
    digest = hashlib.blake2s(key.encode("utf-8"), digest_size=2).digest()
    variant_count = FALLBACK_VARIANT_COUNTS.get(category or "", FALLBACK_VARIANT_COUNT)
    return int.from_bytes(digest, "big") % variant_count + 1


def choose_fallback_image(recipe: dict[str, Any]) -> tuple[str, str]:
    """Return the deterministic local fallback image for a recipe."""
    category = choose_fallback_category(recipe)
    variant = choose_variant(recipe, category)
    return (
        f"{FALLBACK_IMAGE_BASE_URL}/{category}-{variant}.png",
        f"fallback:{category}:{variant}",
    )


def choose_display_image(recipe: dict[str, Any]) -> tuple[str, str]:
    """Return a display URL and provenance without changing the recipe source."""
    for url in recipe.get("image_urls") or []:
        if isinstance(url, str) and url.strip():
            return url.strip(), "original"

    return choose_fallback_image(recipe)


def enrich_recipe_for_display(recipe: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with display-only image data added."""
    display_image_url, image_source = choose_display_image(recipe)
    fallback_image_url, _ = choose_fallback_image(recipe)
    return {
        **recipe,
        "display_image_url": display_image_url,
        "fallback_image_url": fallback_image_url,
        "image_source": image_source,
    }
