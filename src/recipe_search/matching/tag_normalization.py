from recipe_search.settings import PACKAGE_ROOT

"""Conservative tag normalization; never apply to names, ingredients or instructions."""
import html
import json
import re
import unicodedata
from functools import lru_cache

VERSION = "tags-v2-inplace"
EMPTY = {"", "na", "nan", "null", "none"}
SPLITS = {
    "chicken thigh & leg": ["chicken thigh", "chicken leg"],
    "chicken thigh and leg": ["chicken thigh", "chicken leg"],
    "lunch/snacks": ["lunch", "snacks"],
    "broil/grill": ["broil", "grill"],
    "soy/tofu": ["soy", "tofu"],
    "lamb/sheep": ["lamb", "sheep"],
    "yam/sweet potato": ["yam", "sweet potato"],
    "bath/beauty": ["bath", "beauty"],
    "homeopathy/remedies": ["homeopathy", "remedies"],
}
PROTECTED = {"mac & cheese", "macaroni & cheese", "fish & chips", "sweet & sour", "half & half"}
ALIASES = {"snacks": "snack"}


def clean_tag(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", html.unescape(str(value)))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return "" if text in EMPTY else text


def normalize_tags(values):
    if isinstance(values, str):
        values = [values]
    output = []
    for value in values or []:
        # Pipe is an explicit list separator. Slashes require an approved mapping.
        for part in clean_tag(value).split("|"):
            part = part.strip()
            if part in SPLITS:
                pieces = SPLITS[part]
            elif part in PROTECTED:
                pieces = [part.replace("&", "and")]
            else:
                pieces = part.split("&")
            for piece in pieces:
                tag = clean_tag(piece)
                tag = ALIASES.get(tag, tag)
                if tag and tag not in output:
                    output.append(tag)
    return output


@lru_cache(maxsize=1)
def load_rules():
    return json.loads((PACKAGE_ROOT / "config/tag_mapping_v1.json").read_text())["rules"]


def classify_tags(keywords, category):
    # Classification uses whole source labels, never split alternatives as facts.
    source = {
        clean_tag(part) for v in [*(keywords or []), category] for part in clean_tag(v).split("|")
    } - {""}
    result = {
        key: []
        for key in (
            "meal_types",
            "dish_types",
            "cuisines",
            "meal_type_candidates",
            "dish_type_candidates",
        )
    }
    evidence = []
    for rule in load_rules():
        matched = sorted(source.intersection(rule["source_tags"]))
        if not matched:
            continue
        field = rule["field"]
        if rule["value"] not in result[field]:
            result[field].append(rule["value"])
        evidence.append(
            dict(
                field=field,
                value=rule["value"],
                source_tags=matched,
                relation=rule["relation"],
                filter_policy=rule["filter_policy"],
            )
        )
    return {**result, "tag_mapping_evidence": evidence, "tag_normalization_version": VERSION}
