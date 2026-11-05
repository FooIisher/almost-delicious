"""Deterministic, auditable recall relaxation; with original eligibility retained for all relaxed candidates."""
from itertools import combinations
import copy
from constraint_logic import normalized, default_expression, RequiredExpression, references
from time_match import BUCKETS

FIELDS={'total_time':'total_time_minutes','calories':'calories','protein':'proteincontent'}

def numeric_bounds(request):
    rows=[c.model_dump() for c in request.numeric_filters]
    for field,value in [('total_time',request.max_total_time_minutes),('calories',request.max_calories)]:
        if value is not None:rows.append(dict(field=field,operator='lte',value=value,basis='not_applicable' if field=='total_time' else 'per_serving'))
    rows += [dict(field='total_time',operator=op,value=value,basis='not_applicable') for op,value in BUCKETS.get(request.cook_time,[])]
    return rows

def apply_actions(request,actions):
    rows=numeric_bounds(request);expr=request.required_expression or default_expression(request.include_ingredients+(request.category_required or []))
    dropped={normalized(a['value']) for a in actions if a['type']=='drop_ingredient'}
    includes=[n for n in request.include_ingredients if normalized(n) not in dropped]
    if dropped and expr and expr.op=='ingredient' and normalized(expr.ingredient) in dropped:expr=None
    if dropped and expr and expr.op=='AND':
        children=[c for c in expr.children if not(c.op=='ingredient' and normalized(c.ingredient) in dropped)]
        expr=RequiredExpression(op='AND',children=children) if len(children)>1 else children[0] if children else None
    for action in actions:
        if action['type']=='numeric':rows=[c for c in rows if c['field']!=action['field']]+copy.deepcopy(action['to'])
    from recipe_search_api import NumericFilter
    return request.model_copy(update=dict(include_ingredients=includes,required_expression=expr,numeric_filters=[NumericFilter(**c) for c in rows],max_total_time_minutes=None,max_calories=None,cook_time=None))

def plans_for(request):
    expr=request.required_expression or default_expression(request.include_ingredients+(request.category_required or []))
    names=list({normalized(n):n for n in references(expr)}.values());core={normalized(n) for n in request.core_ingredients}
    if len(names)==1:core.add(normalized(names[0]))
    # Only structured dish targets, never the application-generated query.
    from core_policy import intrinsic_match
    for name in names:
        if any(intrinsic_match(name,target) for target in (request.dish_name_target,request.bm25_dish_name) if target):core.add(normalized(name))
    actions=[]
    bounds=numeric_bounds(request)
    for field in dict.fromkeys(c['field'] for c in bounds):
        original=[c for c in bounds if c['field']==field]
        if any(c['operator']=='eq' for c in original):continue
        for factor,level in [(1.2,1),(1.5,3),(None,4)]:
            changed=[]
            if factor:
                for c in original:
                    value=c['value']*factor if c['operator'] in ('lt','lte') else c['value']/factor
                    changed.append({**c,'value':value})
            actions.append(dict(type='numeric',field=field,level=level,ratio=(factor-1) if factor else 1,**{'from':original,'to':changed}))
    if expr and expr.op=='AND':
        for node in expr.children:
            if node.op=='ingredient' and normalized(node.ingredient) not in core and normalized(node.ingredient) in {normalized(n) for n in request.include_ingredients}:
                actions.append(dict(type='drop_ingredient',value=node.ingredient,level=2,ratio=1))
    sole_exception=bool(expr and expr.op=='ingredient' and len(names)==1 and normalized(names[0]) in {normalized(n) for n in request.include_ingredients} and not request.category_required and not bounds and not request.labels)
    if sole_exception:
        actions.append(dict(type='drop_ingredient',value=names[0],level=2,ratio=1,sole_required_exception=True))
    variants=[]
    for count in (1,2):
        for group in combinations(actions,count):
            if count>1 and any(a.get('sole_required_exception') for a in group):continue
            keys=[a.get('field') if a['type']=='numeric' else 'ingredient:'+normalized(a['value']) for a in group]
            if len(set(keys))!=len(keys):continue
            variants.append(dict(plan_id='plan-'+str(len(variants)+1),order=len(variants),actions=list(group),cost=sum(a['level'] for a in group),ratio=sum(a['ratio'] for a in group)))
    return variants,[dict(name=n,protected=normalized(n) in core,sole_core_exception=sole_exception,reason='Core ingredient · sole required ingredient may be relaxed for recall only' if sole_exception else 'Core ingredient' if normalized(n) in core else 'Only top-level AND leaves can be removed') for n in names]

def build_relaxation_aggs(request,build_filters):
    variants,protected=plans_for(request)
    buckets={'strict':build_filters(request) or {'match_all':{}}}
    for plan in variants:buckets[plan['plan_id']]=build_filters(apply_actions(request,plan['actions'])) or {'match_all':{}}
    aggs={'relaxation_plans':{'filters':{'filters':buckets}}}
    numeric_fields=list(dict.fromkeys(c['field'] for c in numeric_bounds(request)))
    if numeric_fields:
        base=request.model_copy(update=dict(numeric_filters=[],max_total_time_minutes=None,max_calories=None,cook_time=None))
        aggs['missing_numeric']={'filter':build_filters(base) or {'match_all':{}},'aggs':{field:({'filter':{'bool':{'should':[{'bool':{'must_not':[{'exists':{'field':FIELDS[field]}}]}},{'range':{FIELDS[field]:{'lte':0}}}], 'minimum_should_match':1}}} if field=='total_time' else {'missing':{'field':FIELDS[field]}}) for field in numeric_fields}}
    return dict(size=0,timeout='800ms',aggs=aggs),variants,protected

def choose_relaxation(variants,counts,target):
    strict=counts['strict'];ordered=sorted(variants,key=lambda p:(len(p['actions']),p['cost'],p['ratio'],counts[p['plan_id']],p.get('order',0)))
    selected=None
    for plan in ordered:
        plan['filter_match_count']=counts[plan['plan_id']];plan['additional_filter_matches']=counts[plan['plan_id']]-strict
        plan['reason']='No increase over strict range' if plan['filter_match_count']<=strict else 'Below target' if plan['filter_match_count']<target else 'Higher-cost alternative'
        if selected is None and plan['filter_match_count']>strict and plan['filter_match_count']>=target:
            selected=plan;plan['reason']='Lowest-cost eligible plan';plan['selected']=True
    if selected:
        for plan in ordered:
            if plan is selected or plan['filter_match_count']<=strict or plan['filter_match_count']<target:continue
            if len(plan['actions'])>len(selected['actions']):plan['reason']='More conditions would change'
            elif plan['cost']>selected['cost']:plan['reason']='Higher action cost'
            elif plan['ratio']>selected['ratio']:plan['reason']='Larger proportional change'
            elif plan['filter_match_count']>selected['filter_match_count']:plan['reason']='More filter matches than needed at the same cost'
            else:plan['reason']='Stable condition-order tie-break'
    return selected

def classify_near_miss(assessment,metadata,expr):
    """Re-evaluate only selected relaxed atoms as pass to test all other requirements."""
    if assessment['status']=='pass' or not metadata or metadata.get('source_level')!='relaxed':return assessment
    from eligibility import decision
    actions=metadata.get('relaxation',[]);checks=copy.deepcopy(assessment['checks']);deviations=[]
    for c in checks:
        allowed=next((a for a in actions if a['type']=='numeric' and c['kind']=='numeric' and a['field']==c['name'] or a['type']=='drop_ingredient' and c['kind']=='ingredient' and c['role']=='required' and normalized(a['value'])==normalized(c['name'])),None)
        if allowed and c['decision']=='fail':
            deviations.append(dict(condition_id=c['constraint_id'],name=c['name'],kind=c['kind'],reason=c['reason'],evidence=c['evidence'],**({'operator':c['operator'],'required_value':c['value'],'actual_value':float(c['evidence'][0]),'difference':abs(float(c['evidence'][0])-c['value'])} if c['kind']=='numeric' and c['evidence'] else {})))
            if c['kind']=='numeric' and c['evidence']:
                actual=float(c['evidence'][0]);unit={'total_time':'min','calories':'kcal / serving','protein':'g / serving'}[c['name']]
                change='above' if c['operator'] in ('lt','lte') else 'below'
                if actual==c['value'] and c['operator'] in ('lt','gt'):
                    comparison='less than' if c['operator']=='lt' else 'more than'
                    deviations[-1]['reason']=f"Exactly {actual:g} {unit}; your request requires {comparison} {c['value']:g} {unit}."
                else:deviations[-1]['reason']=f"{c['name'].replace('_',' ').title()}: {actual:g} {unit}; {abs(actual-c['value']):g} {unit} {change} the original {c['operator']} {c['value']:g} limit."
            if c['kind']=='ingredient' and c.get('status')=='not_matched':deviations[-1]['reason']=f"No {c['name']} in the recorded preparation ingredients."
            c['decision']='pass' 
    # Only a completed semantic judgment gets this alternative-only exception.
    # A locally pending identity must still be checked, and strict candidates
    # never reach this path. Preserve original unknown checks in the result.
    for c in checks:
        if actions and c['kind'] in ('dish_name','dish_type') and c['decision']=='unknown' and c.get('source')=='model' and not c.get('semantic_required'):
            deviations.append(dict(condition_id=c['constraint_id'],name=c['name'],kind=c['kind'],reason=f"Dish type may not fully match the requested {c['name']}; dish identity remains unconfirmed.",evidence=c['evidence'],uncertain=True))
            c['decision']='pass'
    adjusted=decision(assessment['recipe_id'],checks,expr)
    if deviations and adjusted['status']=='pass':return {**assessment,'status':'near_miss','deviations':deviations,'group_key':'|'.join(sorted({('missing:' if d['kind']=='ingredient' else 'numeric:' if d['kind']=='numeric' else 'identity:')+(d['name'] if d['kind']=='numeric' else normalized(d['name'])) for d in deviations})), 'source_plans':metadata.get('source_plans',[]),'relaxation_cost':metadata.get('relaxation_cost',0)}
    if adjusted['status']=='unknown':return {**assessment,'status':'unknown'}
    return assessment


def effective_checks(checks,metadata,expr):
    """Recall relaxation never waives original recommendation requirements."""
    checks=copy.deepcopy(checks)
    actions=(metadata or {}).get('relaxation',[]) if (metadata or {}).get('source_level')=='relaxed' else []
    dropped={normalized(a['value']) for a in actions if a['type']=='drop_ingredient'}
    # A relaxed source alone does not prove absence. Only a complete recorded
    # ingredient list and no unresolved alias/compound evidence can do so.
    for c in checks:
        if c['kind']=='ingredient' and c['role']=='required' and normalized(c['name']) in dropped and c.get('decision')=='unknown' and c.get('local_absence_supported') and not c.get('invalid_evidence'):
            c.update(status='not_matched',decision='fail',semantic_required=False,source='local',reason=f"No {c['name']} in the recorded preparation ingredients.")
    return checks,expr


def assess_candidate(identifier,checks,metadata,expr):
    from eligibility import decision
    effective,expression=effective_checks(checks,metadata,expr)
    for original,updated in zip(checks,effective):original.update(updated)
    outcome=decision(identifier,effective,expression)
    outcome['waived_conditions']=[dict(constraint_id=c['constraint_id'],name=c['name'],reason=c['waiver_reason']) for c in effective if c.get('waived')]
    return {**classify_near_miss(outcome,metadata,expression),'source_level':(metadata or {}).get('source_level','strict')}


def action_key(action):
    return ('numeric:'+action['field']) if action['type']=='numeric' else 'missing:'+normalized(action['value'])


def choose_relaxation_set(variants, counts, target=3, max_plans=3):
    """Select distinct relaxation directions; retain v1 selector for controlled comparisons."""
    strict=counts['strict'];selected=[];used=set()
    ordered=sorted(variants,key=lambda p:(len(p['actions']),p['cost'],p['ratio'],counts[p['plan_id']],p.get('order',0)))
    for plan in ordered:
        plan.update(selected=False,filter_match_count=counts[plan['plan_id']],additional_filter_matches=counts[plan['plan_id']]-strict)
        plan['reason']='Below per-plan minimum' if counts[plan['plan_id']]<target else 'No increase over strict range' if counts[plan['plan_id']]<=strict else 'Not selected'
    def take(plan):
        keys={action_key(a) for a in plan['actions']}
        if plan['filter_match_count']<target or plan['additional_filter_matches']<=0:return
        if keys&used:plan['reason']='Overlaps a selected relaxation direction';return
        if len(selected)>=max_plans:plan['reason']='Plan limit reached';return
        plan.update(selected=True,reason='Distinct eligible relaxation direction',selection_rank=len(selected)+1)
        selected.append(plan);used.update(keys)
    for plan in ordered:
        if len(plan['actions'])==1:take(plan)
    allow_pairs=len(selected)<2
    for plan in ordered:
        if len(plan['actions'])==2:
            if allow_pairs:take(plan)
            elif plan['reason']=='Not selected':plan['reason']='At least two single-condition directions available'
    return selected


def alternative_groups(recipes, assessments, max_groups=3, per_group=2):
    """Actual deviations define membership, independent of recall source plan."""
    groups={}
    for rank,recipe in enumerate(recipes):
        a=assessments[recipe['recipe_id']]
        if a['status']!='near_miss':continue
        key=a.get('group_key') or '|'.join(sorted({('missing:' if d['kind']=='ingredient' else 'numeric:' if d['kind']=='numeric' else 'identity:')+(d['name'] if d['kind']=='numeric' else normalized(d['name'])) for d in a.get('deviations',[])}))
        a['group_key']=key
        if key not in groups:
            missing={d['condition_id'] for d in a.get('deviations',[])}
            def label(c):
                if c['kind']!='numeric':return c['name']
                op={'lt':'<','lte':'≤','gt':'>','gte':'≥','eq':'='}.get(c.get('operator'),'')
                unit={'total_time':'min','calories':'kcal / serving','protein':'g / serving'}.get(c['name'],'')
                return f"{c['name'].replace('_',' ')} {op}{c.get('value'):g} {unit}"
            retained=list(dict.fromkeys(label(c) for c in sorted(a['checks'],key=lambda c:0 if c['kind']=='ingredient' else 1 if c['kind']=='numeric' else 2) if c['role']=='required' and c['constraint_id'] not in missing and c['decision']=='pass' and not (c['kind']=='dish_type' and any(x['kind']=='dish_name' and x['decision']=='pass' and (' '+normalized(c['name'])+' ') in (' '+normalized(x['name'])+' ') for x in a['checks']))))
            differences=list(dict.fromkeys(('without '+d['name']) if d['kind']=='ingredient' else (d['name'].replace('_',' ')+' outside your limit') if d['kind']=='numeric' else 'dish identity not fully confirmed' for d in a.get('deviations',[])))
            groups[key]=dict(group_key=key,retained_requirements=retained,title=('Keeps '+', '.join(retained[:3])+(' + '+str(len(retained)-3)+' more' if len(retained)>3 else '')+' · ' if retained else '')+' / '.join(differences),deviation_count=len(missing),cost=a.get('relaxation_cost',0),first_rank=rank,recipe_ids=[],deviations=a.get('deviations',[]),source_plans=[])
        group=groups[key];group['recipe_ids'].append(recipe['recipe_id'])
        group['source_plans']=list(dict.fromkeys(group['source_plans']+a.get('source_plans',[])))
    return [{**g,'available_count':len(g['recipe_ids']),'recipe_ids':g['recipe_ids'][:per_group]} for g in sorted(groups.values(),key=lambda g:(g['deviation_count'],g['cost'],g['first_rank']))[:max_groups]]


def group_targets_complete(assessments, levels, per_group=2, recipes=None):
    """A source direction is done once each observed deviation group has quota,
    or every candidate belonging to that direction has a completed verdict.
    Directions yielding no candidates are exhausted, not successful quotas.
    """
    plans={p for meta in levels.values() for p in meta.get('source_plans',[])}
    if not plans:return False
    distinct_ids=None
    if recipes is not None:
        from recommendation_dedup import dedupe_ranked
        distinct,_=dedupe_ranked([r for r in recipes if assessments[r['recipe_id']]['status']=='near_miss'])
        distinct_ids={r['recipe_id'] for r in distinct}
    groups={}
    for identifier,a in assessments.items():
        if a['status']=='near_miss' and (distinct_ids is None or identifier in distinct_ids):groups.setdefault(a.get('group_key',''),[]).append(identifier)
    for plan in plans:
        ids=[i for i,m in levels.items() if plan in m.get('source_plans',[]) and i in assessments]
        pending=[i for i in ids if assessments[i]['status'] in ('unknown','not_checked') and any(c.get('semantic_required') for c in assessments[i]['checks'])]
        observed=[rows for rows in groups.values() if any(i in ids for i in rows)]
        if pending and (not observed or any(len(rows)<per_group for rows in observed)):return False
    return True
