# Recipe Search Prototype 1.0

A compact web prototype for comparing BM25, vector, and hybrid recipe retrieval.

## Run

```bash
cd "/path/to/thesis/project/prototype-1.0"
python -m pip install -r requirements.txt
uvicorn recipe_search_api:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

The large source dataset remains at `../data/recipes.parquet`; the ingestion
script uses that location by default so the prototype folder contains only the
application, frontend, and supporting runtime files.

The formal API is available through Swagger documentation at `/docs`:

- `GET /health` — API and Elasticsearch availability.
- `POST /recipes/search` — recipe retrieval.
- `GET /recipes/{recipe_id}` — complete recipe detail.

The older `/api/health` and `/api/search` paths remain as compatibility aliases.
A search request body looks like:

```json
{
  "query": "quick creamy pasta",
  "mode": "hybrid",
  "include_ingredients": ["chicken", "garlic"],
  "exclude_ingredients": ["peanut"],
  "max_total_time_minutes": 30,
  "max_calories": 700,
  "size": 10
}
```

`mode` accepts `bm25`, `vector`, or `hybrid`. Ingredient filters use
case-insensitive substring matching against the indexed `ingredients` field;
every included ingredient is required and every excluded ingredient is removed.
`max_total_time_minutes` and `max_calories` are optional numeric upper bounds.
`max_calories` applies to Food.com-reported calories per serving. The browser's
time buckets use `total_time_minutes`; the API's existing `cook_time` request
field is retained for compatibility.
Recipes missing a selected numeric field are excluded rather than treated as a
match. The browser prototype also displays Elasticsearch health and opens a
full detail card when a recipe title is clicked.

## Elasticsearch configuration

The default connection is `https://localhost:19200`, with the local CA bundle
at `recipe-es-ca.crt`. Override deployment credentials without changing source:

```bash
export ES_USERNAME="elastic"
export ES_PASSWORD="your-password"
export ES_CA_CERTS="/path/to/ca.crt"
```

The `recipes_clean` index must contain `content_vector` embeddings for vector
and hybrid modes. Use `ingest_recipes.py --with-embeddings` to create them.

## Performance optimization notes (deferred)

The prototype exposes embedding, Elasticsearch retrieval, and total timing in
the browser so that performance changes can be measured rather than inferred.
On the current local machine, exploratory searches observed the following
query-dependent ranges:

| Mode | Observed total latency | Main contributor |
| --- | ---: | --- |
| BM25 | about 80–210 ms | Elasticsearch lexical retrieval |
| Vector | about 290–1,020 ms | Query embedding, then kNN retrieval |
| Hybrid | about 1.94 s in one observed query | Query embedding: 1.18 s |

These are exploratory baselines, not service-level guarantees. Planned
optimizations for a later prototype:

1. Add a visible **Fast lexical search** hint or preset that selects BM25 when
   semantic recall is not required.
2. Cache normalized repeated-query embeddings (keyed by model name and query)
   with a bounded TTL/LRU policy; never reuse an embedding after the model is
   changed.
3. Record mode-specific latency percentiles over a fixed acceptance-query set,
   separating embedding from Elasticsearch time.
4. When RRF is introduced, measure the cost of its two retrieval branches and
   in-memory fusion independently; `_msearch` may reduce request overhead but
   does not remove the embedding step.

## Next prototype: RRF hybrid ranking

The next prototype will evaluate **Reciprocal Rank Fusion (RRF)** instead of
the current Elasticsearch score summation for hybrid ranking. The planned
free-tier-compatible flow is:

1. Retrieve lexical BM25 Top-K and vector kNN Top-K independently.
2. Fuse their ranked lists in the API process using the RRF formula
   `1 / (rank_constant + rank)` for each branch.
3. Return the final ranked list together with branch and fusion timing.

This is deliberately deferred: Elasticsearch's native RRF is an Enterprise
feature, while the current local cluster uses the free tier. The two retrieval
branches may be sent together with `_msearch`, but the RRF computation will
remain in application memory.
