"""Run on the VM; verifies versions, auth and a temporary 768-D kNN index."""
import base64
import json
import ssl
import urllib.request
import urllib.error
import uuid
from pathlib import Path

root = Path('/home/azureuser/recipe-search')
env = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines())
context = ssl.create_default_context(cafile=str(root / 'certs/ca/ca.crt'))
auth = base64.b64encode(('elastic:' + env['ELASTIC_PASSWORD']).encode()).decode()

def request(path, body=None, method='GET', authenticated=True):
    headers = {'Content-Type': 'application/json'}
    if authenticated:
        headers['Authorization'] = 'Basic ' + auth
    req = urllib.request.Request('https://localhost:9200' + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers=headers, method=method)
    with urllib.request.urlopen(req, context=context, timeout=60) as response:
        return json.load(response)

assert request('/')['version']['number'] == '9.0.0'
try:
    request('/', authenticated=False)
    raise AssertionError('Unauthenticated request succeeded')
except urllib.error.HTTPError as e:
    assert e.code == 401

index = 'deployment-smoke-' + uuid.uuid4().hex
created = False
try:
    request('/' + index, {'settings': {'number_of_shards': 1, 'number_of_replicas': 0},
                         'mappings': {'properties': {'name': {'type': 'text'},
                            'embedding': {'type': 'dense_vector', 'dims': 768,
                                          'index': True, 'similarity': 'cosine'}}}}, 'PUT')
    created = True
    vector = [1.0] + [0.0] * 767
    request('/' + index + '/_doc/1?refresh=true', {'name': 'recipe deployment test', 'embedding': vector}, 'PUT')
    result = request('/' + index + '/_search', {'knn': {'field': 'embedding', 'query_vector': vector,
                                                     'k': 1, 'num_candidates': 10}}, 'POST')
    assert result['hits']['hits'][0]['_id'] == '1'
    print('PASS: Elasticsearch 9.0.0; TLS; unauthenticated requests rejected; 768-D vector indexing and kNN search')
finally:
    if created:
        request('/' + index, method='DELETE')

with urllib.request.urlopen('http://127.0.0.1:5601/api/status', timeout=30) as response:
    status = json.load(response)
assert status['status']['overall']['level'] == 'available', status['status']['overall']
# Authenticated response includes the version even when anonymous status is redacted.
req = urllib.request.Request('http://127.0.0.1:5601/api/status', headers={'Authorization': 'Basic ' + auth})
with urllib.request.urlopen(req, timeout=30) as response:
    status = json.load(response)
assert status['version']['number'] == '9.0.0'
print('PASS: Kibana 9.0.0 available')
print(json.dumps(request('/_cluster/health'), indent=2))
