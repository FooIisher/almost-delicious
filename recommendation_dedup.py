"""Conservative two-signal deduplication, preserving input rank and provenance."""
import json,re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from recipe_text import clean_text
from ingredient_sources import values
RULES=json.loads((Path(__file__).parent/'config/recommendation_dedup.json').read_text())
@lru_cache(maxsize=4096)
def key(text):return ' '.join(re.findall(r'[^\W_]+',clean_text(str(text)).casefold()))
def similarity(a,b):
    x,y=key(a.get('name','')),key(b.get('name',''))
    name=max(SequenceMatcher(None,x,y).ratio(),SequenceMatcher(None,' '.join(sorted(x.split())),' '.join(sorted(y.split()))).ratio()) if x and y else 0
    left={key(v) for v in values(a,preparation_only=True) if key(v)};right={key(v) for v in values(b,preparation_only=True) if key(v)}
    ingredient=len(left&right)/len(left|right) if left and right else 0
    return name,ingredient

def dedupe_ranked(recipes,seed=()):
    kept=[];comparisons=list(seed);removed=[]
    for recipe in recipes:
        duplicate=None
        for earlier in comparisons:
            name,ingredient=similarity(recipe,earlier)
            if name>=RULES['name_similarity_threshold'] and ingredient>=RULES['ingredient_similarity_threshold']:
                duplicate=dict(recipe_id=recipe['recipe_id'],kept_recipe_id=earlier['recipe_id'],name_similarity=round(name,4),ingredient_similarity=round(ingredient,4));break
        if duplicate:removed.append(duplicate)
        else:kept.append(recipe);comparisons.append(recipe)
    return kept,removed
