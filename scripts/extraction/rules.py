"""Rule-based extraction (rule-v1) of ingredients mentioned in instructions.

No LLM calls. A term is reported only when the recipe's ingredient list does not
already cover it. The behaviour matches the original 2026-10-23 extraction run.
"""

import re

from supplement import SUPPLEMENT

VERSION = "rule-v1"
STOP = set(
    "water ice salt pepper mixture mix sauce dressing filling topping stock seasoning batter "
    "dough glaze crust cream oil fat liquid juice meat flour sugar orange green red yellow "
    "brown white black golden pink purple".split()
)
KITCHEN_ITEMS = [
    "parchment paper",
    "wax paper",
    "waxed paper",
    "aluminum foil",
    "foil",
    "plastic wrap",
    "paper towel",
    "toothpick",
    "toothpicks",
    "skewer",
    "skewers",
    "cheesecloth",
    "kitchen twine",
    "string",
    "paper",
    "ice cube",
]
EQUIPMENT = set(
    "maker machine scoop mold mould pan dish bowl sheet tin skillet pot cutter press "
    "container jar bag".split()
)
HEDGE = re.compile(
    r"\b(serve|serving|garnish|optional|option|variation|if desired|if using|if you|"
    r"alternative|you can use|or use|substitut|instead of|on the side|accompan)",
    re.I,
)
SEGMENT = re.compile(r"[,;:.()!?/]")


def singular(word):
    if word in ("leaves", "halves", "loaves"):
        return word[:-3] + "f"
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("oes", "ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def norm(text):
    return " ".join(singular(word) for word in re.findall("[a-z]+", text.lower()))


class Extractor:
    """Term tables built from the generated vocabulary's ``ingredients`` field."""

    def __init__(self, vocabulary_ingredients):
        kitchen = {norm(item) for item in KITCHEN_ITEMS}
        self.terms = {}
        for gram in {norm(name) for name in vocabulary_ingredients}:
            words = len(gram.split())
            if (
                1 <= words <= 2
                and gram not in STOP
                and "water" not in gram
                and gram not in kitchen
                and len(gram) > 2
            ):
                self.terms[gram] = gram
        for canonical, forms in SUPPLEMENT.items():
            for form in forms:
                self.terms[norm(form)] = canonical
        self.unigrams = {gram for gram in self.terms if " " not in gram}
        self.supplement_forms = {norm(form) for forms in SUPPLEMENT.values() for form in forms}

    def extract(self, recipeid, parts, quantities, instructions):
        listed, listed_tokens = set(), set()
        for part in parts:
            words = norm(part).split()
            listed_tokens.update(words)
            for size in (1, 2, 3):
                for i in range(len(words) - size + 1):
                    listed.add(" ".join(words[i : i + size]))
        found = {}
        for sentence in instructions:
            for segment in SEGMENT.split(sentence):
                words = norm(segment).split()
                grams = [(" ".join(words[i : i + 2]), i + 2) for i in range(len(words) - 1)]
                grams += [(word, i + 1) for i, word in enumerate(words)]
                bigram_hits = set()
                for gram, end in grams:
                    if end < len(words) and words[end] in EQUIPMENT:
                        continue
                    if gram not in self.terms:
                        continue
                    if " " not in gram and any(gram in hit.split() for hit in bigram_hits):
                        continue
                    if " " in gram:
                        bigram_hits.add(gram)
                    canonical = self.terms[gram]
                    if (
                        norm(canonical) in listed
                        or gram in listed
                        or all(word in listed_tokens for word in gram.split())
                    ):
                        continue
                    if gram not in self.supplement_forms:
                        food = [word for word in gram.split() if word in self.unigrams]
                        if food and all(word in listed_tokens for word in food):
                            continue
                    if canonical not in found:
                        found[canonical] = dict(
                            ingredient=canonical,
                            text=sentence.strip()[:200],
                            hedged=bool(HEDGE.search(sentence)),
                        )
        return dict(
            recipeid=str(recipeid),
            extract_ingredients=sorted(found),
            extract_evidence=[found[key] for key in sorted(found)],
            ingredient_parts_count=len(parts),
            ingredient_quantities_count=len(quantities),
            ingredient_list_incomplete=len(parts) < len(quantities),
            extraction_version=VERSION,
        )
