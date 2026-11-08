from recipe_search.settings import get_settings

"""Offline mapping: recipes without images -> a similar recipe that has a real photo.

Levels (first hit wins):
  L1  same cleaned name
  L2  same head phrase (last two words of the name before with/in/over/on/topped/served)
  L3  same dish form + same main ingredient, only when name/ingredient similarity is high enough
Within a level the donor with the best 0.6*name_jaccard + 0.4*ingredient_jaccard wins
(ties: more reviews). Name-based only; vector confirmation can be added later.

Usage (from the repository root):
  uv run python scripts/build_image_fallback.py

Reads DATA_DIR/recipes.parquet and writes only the mapping
var/derived/image_fallback_v2.sqlite; summary counts are printed, not saved.
No images are downloaded or stored: the mapping holds photo URLs.
"""

import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict

DATA = str(get_settings().data_file("recipes.parquet", required=True))
OUT_DIR = str(get_settings().derived_dir)
VERSION = "image_fallback_v2"
MAX_DONORS = 60  # donors kept per key (most-reviewed first)
L3_MIN_SCORE = 0.35  # L3 only when similarity is convincing
# Head phrases too broad to identify a dish; they skip L2.
GENERIC_HEADS = {
    "chicken dinner",
    "easy dinner",
    "main dish",
    "side dish",
    "one dish",
    "dish meal",
    "family dinner",
    "weeknight dinner",
    "quick dinner",
    "dinner idea",
    "party food",
    "lunch box",
    "kid friendly",
    "game day",
}

ADJ = set(
    "easy best quick simple simply super ultimate perfect classic basic homemade home made healthy healthier low fat lowfat "
    "light lite delicious yummy tasty amazing awesome favorite favourite my our the a an and of for style old fashioned "
    "fashion fabulous famous special mom moms grandma grandmas nana nanas new great real really good fast minute minutes "
    "crock pot crockpot slow cooker oven baked recipe".split()
)
CUT = re.compile(r"\b(with|in|over|on|topped|served|w)\b")
FORMS = [
    ("stirfry", r"\bstir ?fr(y|ied)\b|\bwok\b"),
    ("soup", r"\b(soup|stew|chowder|chili|bisque|gumbo)\b"),
    ("salad", r"\bsalad\b"),
    ("pasta", r"\b(pasta|spaghetti|lasagna|penne|noodles?|macaroni|fettuccine|ravioli)\b"),
    ("drink", r"\b(smoothie|shake|juice|punch|lemonade|cocktail|martini|tea|coffee)\b"),
    ("sandwich", r"\b(sandwich|burger|wrap|panini|sliders?)\b"),
    ("cake", r"\b(cake|cupcakes?|cheesecake)\b"),
    ("cookie", r"\b(cookies?|brownies?|bars?)\b"),
    ("pie", r"\b(pie|tart|cobbler|crisp)\b"),
    ("bread", r"\b(bread|muffins?|rolls?|biscuits?|scones?|loaf)\b"),
    ("casserole", r"\b(casserole|bake|gratin)\b"),
    ("rice", r"\b(rice|risotto|pilaf|paella)\b"),
    ("sauce", r"\b(sauce|dressing|marinade|dip|salsa|gravy)\b"),
    ("breakfast", r"\b(pancakes?|waffles?|omelet+e?|frittata|french toast)\b"),
    ("curry", r"\bcurry\b"),
    ("pizza", r"\bpizza\b"),
    ("taco", r"\b(tacos?|burritos?|enchiladas?|quesadillas?|fajitas?)\b"),
]
MAIN = (
    "chicken beef pork turkey lamb shrimp salmon tuna fish crab sausage bacon ham tofu bean lentil potato broccoli spinach "
    "mushroom zucchini corn tomato apple banana strawberry blueberry lemon orange pumpkin chocolate peanut cheese egg rice "
    "pasta cabbage carrot cauliflower eggplant pineapple cherry coconut oat"
).split()


def words(text):
    t = str(text).lower()
    t = re.sub(r"\b\w+'s\b", " ", t)
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"&\w+;", " ", t)
    return [w for w in re.sub(r"[^a-z ]", " ", t).split() if w not in ADJ and len(w) > 1]


def sing(w):
    return (
        w[:-3] + "y"
        if w.endswith("ies")
        else w[:-2]
        if w.endswith(("oes", "ches", "shes"))
        else w[:-1]
        if w.endswith("s") and not w.endswith("ss")
        else w
    )


def head(name):
    t = str(name).lower()
    t = re.sub(r"\(.*?\)", " ", t)
    m = CUT.search(t)
    w = [sing(x) for x in words(t[: m.start()] if m and m.start() > 0 else t)]
    key = " ".join(w[-2:]) if len(w) >= 2 else None
    return None if key in GENERIC_HEADS else key


def base_name(name):
    """Name before with/in/over...: the dish itself, not its sauce or topping."""
    t = re.sub(r"\(.*?\)", " ", str(name).lower())
    m = CUT.search(t)
    return t[: m.start()] if m and m.start() > 0 else t


def form(name):
    n = str(name).lower()
    return next((f for f, p in FORMS if re.search(p, n)), None)


def parts(raw):
    return [p.strip().lower() for p in re.findall(r'"([^"]*)"', str(raw))] or (
        [str(raw).strip().lower()]
        if raw and str(raw) not in ("character(0)", "None", "nan")
        else []
    )


def main_ing(ws, ps):
    for w in ws + [x for p in ps for x in p.split()]:
        if sing(w) in MAIN:
            return sing(w)
    return None


def first_url(raw):
    m = re.search(r'https?://[^"\s]+', str(raw))
    return m.group(0) if m else None


def jac(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def load_recipes():
    import pyarrow.parquet as pq

    t = pq.read_table(
        DATA, columns=["recipeid", "name", "images", "recipeingredientparts", "reviewcount"]
    ).to_pydict()
    rows = []
    for rid, name, img, ing, rc in zip(
        t["recipeid"], t["name"], t["images"], t["recipeingredientparts"], t["reviewcount"]
    ):
        ws = [sing(w) for w in words(name)]
        ps = parts(ing)
        f = form(base_name(name))
        m = main_ing([sing(w) for w in words(base_name(name))], ps)
        rows.append(
            dict(
                id=rid,
                name=name,
                url=first_url(img),
                ws=frozenset(ws),
                ing=frozenset(ps),
                rc=rc or 0,
                k1=" ".join(ws) or None,
                k2=head(name),
                k3=f"{f}|{m}" if f and m else None,
            )
        )
    return rows


def donor_index(rows):
    """Recipes with a photo, grouped by L1/L2/L3 key; most-reviewed first."""
    donors = {k: defaultdict(list) for k in ("k1", "k2", "k3")}
    for r in rows:
        if r["url"]:
            for k in donors:
                if r[k]:
                    donors[k][r[k]].append(r)
    for k in donors:
        for lst in donors[k].values():
            lst.sort(key=lambda r: -r["rc"])
            del lst[MAX_DONORS:]
    return donors


def best_donor(r, donors):
    for level, k in (("L1", "k1"), ("L2", "k2"), ("L3", "k3")):
        cands = donors[k].get(r[k]) if r[k] else None
        if not cands:
            continue
        best = max(
            cands,
            key=lambda c: (0.6 * jac(r["ws"], c["ws"]) + 0.4 * jac(r["ing"], c["ing"]), c["rc"]),
        )
        score = round(0.6 * jac(r["ws"], best["ws"]) + 0.4 * jac(r["ing"], best["ing"]), 3)
        if level == "L3" and score < L3_MIN_SCORE:
            continue
        return level, best, score
    return None


def write_mapping(mapped):
    # Build in a short-lived system temp folder (some synced folders break SQLite
    # locking), then copy the finished file to var/derived.
    os.makedirs(OUT_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, f"{VERSION}.sqlite")
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE fallback (recipeid INTEGER PRIMARY KEY, image_url TEXT NOT NULL, "
            "level TEXT, score REAL, image_recipeid INTEGER, image_name TEXT)"
        )
        con.executemany("INSERT INTO fallback VALUES (?,?,?,?,?,?)", mapped)
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO meta VALUES ('version', ?)", (VERSION,))
        con.commit()
        con.close()
        target = os.path.join(OUT_DIR, f"{VERSION}.sqlite")
        shutil.copyfile(db, target)
    return target


def main():
    rows = load_recipes()
    donors = donor_index(rows)
    targets = [r for r in rows if not r["url"]]
    print(f"{len(rows)} recipes, {len(targets)} without a photo; matching...", flush=True)
    mapped, levels, reuse = [], defaultdict(int), defaultdict(int)
    for i, r in enumerate(targets, 1):
        hit = best_donor(r, donors)
        if hit:
            level, best, score = hit
            mapped.append((r["id"], best["url"], level, score, best["id"], best["name"]))
            levels[level] += 1
            reuse[best["id"]] += 1
        if i % 50000 == 0:
            print(f"  {i}/{len(targets)}", flush=True)
    target = write_mapping(mapped)
    summary = dict(
        version=VERSION,
        targets=len(targets),
        mapped=len(mapped),
        mapped_pct=round(100 * len(mapped) / len(targets), 1) if targets else 0,
        by_level=dict(levels),
        distinct_donor_images=len(reuse),
    )
    print(json.dumps(summary, ensure_ascii=False))
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
