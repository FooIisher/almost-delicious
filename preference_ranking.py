"""Explainable reranking over the complete RRF candidate union."""
import json
import math
from pathlib import Path
RULES = json.loads((Path(__file__).parent / "config/preference_rules.json").read_text())

def rerank(rows, request):
    ceiling = (request.bm25_boost + request.vector_boost) / (request.rrf_k + 1)
    groups = {name: getattr(request, 'preference_' + name) for name in
              ('available', 'prefer', 'avoid', 'cuisine', 'meal_type', 'dish_type', 'healthy', 'quick', 'easy')}
    weights = {name: getattr(request, 'preference_weight_' + name) for name in groups}
    positives = sum(weights[name] for name, values in groups.items() if name != 'avoid' and values)
    for row in rows:
        source = row['hit']['_source']
        def values(field):
            value = source.get(field) or []
            return [str(x).casefold() for x in (value if isinstance(value, list) else [value])]
        tags = set(values('keywords') + values('recipecategory'))
        ingredients = values('ingredients')
        evidence = []
        score = 0.0
        for name, requested in groups.items():
            if not requested:
                continue
            matched = [x for x in requested if (any(x.casefold() in ingredient for ingredient in ingredients)
                       if name in ('available', 'prefer', 'avoid') else x.casefold() in tags)]
            checks = []
            if name == 'healthy':
                for rule in RULES['healthy']:
                    value = source.get(rule['field'])
                    valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
                    passed = valid and (value >= rule['threshold'] if rule['operator'] == 'gte' else value <= rule['threshold'])
                    checks.append({**rule, 'value': value if valid else None, 'status': 'met' if passed else 'not_met' if valid else 'missing'})
                matched = [f"{x['field']}: {x['value']} {x['unit']}" for x in checks if x['status']=='met']
                match_score = len(matched) / len(RULES['healthy'])
            elif name == 'quick':
                value = source.get('total_time_minutes')
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
                matched = [f'total time: {value} min'] if valid and value <= RULES['quick_minutes'] else []
                checks = [dict(field='total_time_minutes', value=value if valid else None, threshold=RULES['quick_minutes'], unit='minutes', status='met' if matched else 'not_met' if valid else 'missing')]
                match_score = float(bool(matched))
            elif name == 'easy':
                matched = ['easy'] if 'easy' in tags else []
                match_score = float(bool(matched))
            else:
                match_score = len(matched) / len(requested)
            contribution = (-weights[name] * match_score if name == 'avoid'
                            else weights[name] * match_score / positives if positives else 0.0)
            score += contribution
            evidence.append(dict(group=name, requested=requested, matched=matched, weight=weights[name],
                                 match_score=match_score, checks=checks, contribution=contribution,
                                 final_contribution=request.preference_lambda * contribution))
        row.update(rrf_rank=row['rank'], normalized_rrf=row['rrf_score']/ceiling,
                   preference_score=score, preference_evidence=evidence)
        rating = source.get('aggregatedrating')
        valid_rating = isinstance(rating, (int, float)) and not isinstance(rating, bool) and math.isfinite(rating)
        rating_factor = {3: 0.6, 4: 0.8, 5: 1.0}.get(rating, 0.0) if valid_rating else 0.0
        row['rating_factor'] = rating_factor
        row['rating_bonus'] = request.rating_boost * rating_factor
        row['rating_value'] = rating if valid_rating else None
        row['final_score'] = row['normalized_rrf'] + request.preference_lambda * score + row['rating_bonus']
    rows.sort(key=lambda row: (-row['final_score'], row['rrf_rank']))
    for rank, row in enumerate(rows, 1):
        row['rank'] = rank
    return rows
