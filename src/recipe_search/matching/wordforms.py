from recipe_search.settings import PACKAGE_ROOT
import json
import re
from functools import lru_cache

VOCABULARY_PATH = PACKAGE_ROOT / "config" / "bm25_vocabulary.json"
INVARIANT = {
    "fish",
    "sheep",
    "deer",
    "species",
    "seafood",
    "rice",
    "beef",
    "pork",
    "asparagus",
    "couscous",
    "hummus",
    "molasses",
    "greens",
    "watercress",
}
IRREGULAR = {
    "potato": "potatoes",
    "tomato": "tomatoes",
    "leaf": "leaves",
    "loaf": "loaves",
    "knife": "knives",
    "half": "halves",
}


def candidates(phrase):
    phrase = " ".join(phrase.casefold().split())
    prefix, separator, head = phrase.rpartition(" ")
    forms = {head}
    if not re.fullmatch("[a-z]+", head) or head in INVARIANT:
        return {phrase}
    reverse = {plural: singular for singular, plural in IRREGULAR.items()}
    if head in IRREGULAR:
        forms.add(IRREGULAR[head])
    elif head in reverse:
        forms.add(reverse[head])
    elif head.endswith("ies"):
        forms.add(head[:-3] + "y")
        forms.add(head[:-1])
    elif head.endswith(("ches", "shes", "xes", "zes", "sses")):
        forms.add(head[:-2])
    elif head.endswith("s") and not head.endswith(("ss", "us", "is")):
        forms.add(head[:-1])
    elif head.endswith("y") and len(head) > 1 and head[-2] not in "aeiou":
        forms.add(head[:-1] + "ies")
    elif head.endswith(("ch", "sh", "x", "z", "ss")):
        forms.add(head + "es")
    elif not head.endswith(("s", "us", "is")):
        forms.add(head + "s")
    return {prefix + separator + form for form in forms}


@lru_cache(maxsize=1)
def vocabulary():
    data = json.loads(VOCABULARY_PATH.read_text())
    return {field: set(values) for field, values in data["fields"].items()}


def matching_forms(field, phrase):
    phrase = " ".join(phrase.casefold().split())
    present = candidates(phrase).intersection(vocabulary()[field])
    return sorted(present) if present else [phrase]


def distinct_groups(field, phrases):
    groups = {}
    for phrase in phrases:
        if phrase.strip():
            forms = matching_forms(field, phrase)
            groups.setdefault(tuple(forms), forms)
    return list(groups.values())
