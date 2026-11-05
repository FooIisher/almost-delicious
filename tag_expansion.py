"""Shared tag boosts; heuristic tags never establish final eligibility."""
import json
from pathlib import Path
from ingredient_match import norm
DATA=json.loads((Path(__file__).parent/'config/tag_mapping_v1.json').read_text())
def expand_tags(field,value):
    result={norm(value):1.0}
    for rule in DATA['rules']:
        if rule['field'] not in (field,field.replace('types','type_candidates')) or norm(rule['value'])!=norm(value):continue
        weight=.35 if rule.get('relation') in ('heuristic_candidate','ambiguous_group') else 1.0
        for tag in rule['source_tags']:result[norm(tag)]=max(result.get(norm(tag),0),weight)
    return list(result.items())
def tag_matches(field,value,tags):
    available={norm(t):t for t in tags}
    found=[(available[tag],weight) for tag,weight in expand_tags(field,value) if tag in available]
    return found,max((w for _,w in found),default=0.0)
