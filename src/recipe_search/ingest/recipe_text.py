"""Display-only source text repair; never mutate the ES record or evidence input."""

import html
import re

from ftfy import fix_text

TEXT_FIELDS = {
    "name",
    "description",
    "ingredients",
    "instructions",
    "keywords",
    "recipecategory",
    "extract_ingredients",
}


def clean_text(value):
    if not isinstance(value, str):
        return value
    text = value
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    if text.isascii():
        return text
    text = fix_text(text, unescape_html=False)
    # Replacement characters have lost information. Repair only unambiguous
    # conventional contractions; leave other damaged characters visible.
    text = re.sub(
        r"\b((?:do|does|did|is|are|was|were|has|have|had|ca|could|wo|would|should|must|need|ought)n)\ufffd(t)\b",
        r"\1'\2",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(it|that|there|what|he|she|who|let|here)\ufffd(s)\b", r"\1'\2", text, flags=re.I
    )
    return text


def clean_recipe(recipe):
    return {
        key: ([clean_text(x) for x in value] if isinstance(value, list) else clean_text(value))
        if key in TEXT_FIELDS
        else value
        for key, value in recipe.items()
    }
