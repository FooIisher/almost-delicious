"""Give synthetic candidates distinct identities when testing batching, not dedup."""
import hashlib

def distinct_recipe(doc):
    rid=str(doc['_id'])
    return {**doc,'_source':{**doc['_source'],'name':'Soup '+hashlib.sha256(rid.encode()).hexdigest()[:24]}}
