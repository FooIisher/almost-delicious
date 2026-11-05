"""Non-semantic recovery and user-facing summaries. Never infer eligibility."""
import json

def index_assessments(rows,expected_ids):
    if isinstance(rows,dict):
        rows=[{'recipe_id':k,**v} for k,v in rows.items() if isinstance(v,dict)]
    if not isinstance(rows,list):raise ValueError('Semantic output must contain an assessments array or ID-keyed object')
    indexed={i:[] for i in expected_ids};warnings=[]
    for row in rows:
        if not isinstance(row,dict):warnings.append('Ignored malformed semantic assessment without an ID.');continue
        identifier=row.get('recipe_id')
        if isinstance(identifier,int) and not isinstance(identifier,bool):identifier=str(identifier)
        if isinstance(identifier,str):identifier=identifier.strip()
        if identifier not in indexed:
            warnings.append(f'Ignored semantic assessment for unknown recipe ID {str(identifier)[:100]}.');continue
        row={**row,'recipe_id':identifier}
        if any(json.dumps(prior,sort_keys=True)==json.dumps(row,sort_keys=True) for prior in indexed[identifier]):
            warnings.append(f'Ignored identical duplicate assessment for recipe {identifier}.');continue
        indexed[identifier].append(row)
    return indexed,warnings

def tradeoff_summary(count,alternatives,assessments):
    directions=[]
    for item in alternatives:
        for d in assessments[item.recipe_id].get('deviations',[]):
            if d['kind']=='ingredient':phrase='without '+d['name']
            elif d['kind']=='numeric':
                if d['name']=='total_time':phrase='with more cooking time' if d.get('operator') in ('lt','lte') else 'with less total time'
                else:phrase='with a different '+d['name'].replace('_',' ')+' range'
            else:phrase='with a slightly different dish identity'
            if phrase not in directions:directions.append(phrase)
    choices=', '.join(directions[:-1])+' or '+directions[-1] if len(directions)>1 else directions[0] if directions else 'with a small adjustment to your requirements'
    if count:return f"I found {count} confirmed {'recipe' if count==1 else 'recipes'} for you, along with alternatives {choices}. Each group below explains the tradeoff."
    return "Among the recipes we checked, we didn't find a confirmed match for all your requirements. If you're open to alternatives "+choices+", the groups below show your options."

def final_summary(summary,count,alternatives,assessments):
    if alternatives:return tradeoff_summary(count,alternatives,assessments)
    if isinstance(summary,str) and summary.strip():return summary.strip()
    if count:return f"I found {count} {'recipe' if count==1 else 'recipes'} that meet your checked requirements. See each recipe below for its individual matches."
    return 'No confirmed recommendations are available from the checked recipes. Review the candidate checks or revise your request.'
