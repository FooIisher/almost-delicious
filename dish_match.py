"""One explicit dish-type evidence rule for qualification and preference ranking."""
from ingredient_match import norm
from wordforms import candidates

def dish_type_evidence(target,name,tags):
    forms={norm(s) for s in candidates(norm(target))}
    return list(dict.fromkeys(value for value in list(tags)+[name] if value and any((' '+form+' ') in (' '+norm(value)+' ') for form in forms)))
