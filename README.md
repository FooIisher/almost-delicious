# Recipe Search Prototype 1.1 — custom RRF

This directory is an independent copy of the 1.0 application and frontend.
The original `../prototype-1.0` is unchanged. The current increment implements
observable RRF retrieval and a Jev intent interpretation interface. Automatic
application of parsed constraints to search filters remains future work.

## Run

```bash
cd "/path/to/thesis/project/prototype-1.1"
python -m pip install -r requirements.txt
python -m uvicorn recipe_search_api:app --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001> or API docs at <http://127.0.0.1:8001/docs>.
This workspace was verified using `/opt/anaconda3/bin/python`.
Port 8001 allows 1.0 to continue using port 8000.

The existing `recipes_clean` index and `content_vector` embeddings are reused;
no reindexing or data mutation is needed. Elasticsearch uses the existing local
HTTPS tunnel at `https://localhost:19200`. See `../../infra/azure-elastic/README.md`
for its setup. `ES_USERNAME`, `ES_PASSWORD` and `ES_CA_CERTS` can override the
inherited connection configuration. The BGE model is `BAAI/bge-base-en-v1.5`.

## Retrieval behavior

Hybrid previously sent `query` and `knn` in one Elasticsearch request and used
ES score combination. Version 1.1 sends independent BM25 and vector requests,
then applies weighted RRF in Python:

```text
RRF(recipe) = bm25_boost / (k + bm25_rank) + vector_boost / (k + vector_rank)
```

An absent branch contributes zero. Ranks start at 1. IDs are normalized to
strings from `source.recipeid`, falling back to ES `_id`; ingestion writes
`_id = str(recipeid)`. Within each branch the first occurrence is retained and
unique candidates receive contiguous ranks. Across branches each ID produces
one result. BM25's source/highlights are preferred for shared candidates.

Sort order is full-precision RRF descending, best branch rank ascending, then
canonical recipe ID in lexical order ascending. Original ES scores never
affect fusion. Identical ordered input lists yield identical output; approximate
vector retrieval itself can change candidates across runs or index changes.
Different recipes with the same title remain separate when their IDs differ.

Both branches use the same prepared query and hard filters. In parallel mode,
BM25 starts alongside the complete vector path, including model loading and
query embedding. Serial mode calls the same functions consecutively.

## API

- `POST /recipes/search` — JSON result (`/api/search` remains an alias).
- `POST /api/search/stream` — SSE progress and the same final result fields.
- `GET /recipes/{recipe_id}` — recipe detail.
- `GET /health` — actual Elasticsearch connectivity.
- `POST /intent/parse` — validated Jev interpretation for the current query.

Example body:

```json
{
  "query": "chicken",
  "mode": "hybrid",
  "include_ingredients": ["chicken"],
  "exclude_ingredients": ["peanut"],
  "max_total_time_minutes": 30,
  "max_calories": 700,
  "size": 20,
  "rrf_k": 1,
  "bm25_boost": 1,
  "vector_boost": 1,
  "bm25_candidates": 50,
  "vector_candidates": 50,
  "vector_num_candidates": 250,
  "execution": "parallel",
  "branch_timeout_seconds": 30
}
```

`mode` is `bm25`, `vector` or `hybrid`; `execution` is `parallel` or `serial`.
Each Hybrid candidate count must be at least `size`. Candidate counts are
limited to 500 per branch; `size` is 1–50. `rrf_k` is an integer from 1–10000.
Boosts default to 1 and must be finite positive numbers. Results default to 20;
`rrf_k` defaults to 1. In Vector mode, kNN exploration defaults to 50. Hybrid
keeps exploration internal, defaulting to max(250, vector_candidates). Explicit
API exploration values are still supported.
The independent kNN exploration count must be at least the requested vector
candidate count. Branch deadlines are greater than 0 and at most 120 seconds.
Invalid settings return HTTP 422 with field validation information.

Responses include:

- `mode` (requested), `effective_mode`, `execution`, `warnings`.
- `branches`: completion/failure/timeout, elapsed time and candidate count.
- `effective_filters`: actual filters used, echoed for the frontend.
- `candidate_counts`: BM25, vector and deduplicated union counts.
- `rrf`: configuration snapshot, or null outside Hybrid mode.
- Each fused result: final rank, recipe ID, both branch ranks and raw scores,
  both RRF contributions, and `rrf_score`. Missing ranks/scores are null.
  `score` aliases the RRF score and `score_type` is `rrf`.

For Hybrid, `match_result_size.scope = candidate_union`: this is **not** the
number of matches in the full index. BM25-only can report total lexical matches;
vector-only reports returned candidates. The frontend labels these separately.

## Filters and failure behavior

The inherited ingredient filters use case-insensitive substring matching; every
included ingredient is required and excluded ingredients are forbidden. Numeric
filters use total minutes and calories per serving. Missing selected numeric
fields are excluded. The old `cook_time` time-bucket field still refers to total
time. Intent analysis is a separate preview; no allergy inference or new nutrition filters are added.

If one Hybrid branch fails or exceeds its deadline, the surviving list still
uses its one-branch RRF contribution; the response and page explicitly indicate
BM25-only or vector-only degraded results. A successful empty list is not a
failure. If all requested branches fail, JSON returns HTTP 502; an already-open
SSE connection sends an error event. Partial ES responses (`timed_out` or failed
shards) are rejected rather than presented as successful recall.

Deadlines include worker queue time and embedding. There are four recall workers
and at most eight admitted jobs per API process. Requests beyond that bound
receive explicit branch failure (`CapacityExceeded`). Python cannot terminate
an in-progress model call: timed-out work can finish in the background and retains
its admission slot until then. It does not block the response or emit late UI
updates. ES retries are disabled for these branch requests.

## Timings and frontend

| Field | Measured interval |
| --- | --- |
| `bm25_recall_ms` | BM25 submission through usable, validated candidates, including queue time |
| `vector_recall_ms` | Vector submission through usable candidates, including queueing, loading/embedding and query |
| `query_embedding_ms` | Model access/loading plus query encoding |
| `bm25_query_ms`, `vector_query_ms` | Client access and the respective ES request, not ES internal `took` |
| `rrf_ms` | RRF deduplication, contribution calculation, ordering and final truncation |
| `search_total_ms` | Shared filter preparation through formatted search results; independently measured wall time |
| `backend_request_ms` | API handler through result preparation, excluding response transfer |
| Browser end-to-end | Browser submission through receipt of the final SSE response |

Timings use monotonic clocks and milliseconds. They are not added to derive the
parallel total. Skipped/unavailable timings are null and displayed as skipped or
an em dash; failed or timed-out branches also carry explicit status. Breakdown
timings from failed branches are unavailable. Network transfer, serialization
and browser receipt can make browser time exceed backend time.

Retrieval settings shows only the current mode’s controls, in this order:

- BM25: Results (20).
- Vector: Results (20), kNN exploration candidates (50).
- Hybrid: Results (20), Execution (Parallel), BM25 candidates (50), Vector candidates (50), RRF k (1),
  BM25 boost (1), Vector boost (1).

Hidden controls are disabled and omitted from browser requests. Execution defaults
to parallel; Hybrid exposes Serial (comparison) in the page and API. Values are
preserved when switching modes.

The existing page is retained with additions: Retrieval settings, three recall/
fusion progress indicators, expandable timing details, degradation banners, and
per-recipe Ranking evidence tables. Manual filters and recipe detail dialogs
continue to work. Natural-language constraints can be inspected in the intent panel,
but search continues to use the raw query and manually configured filters.

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node --check web/app.js
python scripts/smoke_search.py --output verification/live-smoke-connected.json
```

The 35 offline tests cover hand-calculated fusion, duplicate/missing IDs,
tie-breaking, input preservation, parallel embedding, shared filters,
completion order, bounded admission, deadlines, degradation, empty results,
single modes, request validation and JSON/SSE consistency.

The live smoke runner validates real returned IDs, fusion scores and selected
ingredient/numeric constraints. It records full responses and timing data.
See `verification/README.md` for the observed results and limits. Smoke runs are
not a statistically controlled benchmark and do not establish a general speedup.

## Files

| File | Responsibility |
| --- | --- |
| `rrf.py` | Pure deterministic fusion and ID deduplication |
| `retrieval_execution.py` | Bounded serial/parallel scheduling and deadlines |
| `recipe_search_api.py` | Shared filters, branch queries, result contract and API |
| `web/` | Independent frontend, styles and local image assets |
| `tests/` | Offline correctness and integration checks |
| `scripts/smoke_search.py` | Repeatable read-only live checks |
| `semantic_search.py`, `search_recipes.py` | Inherited ES/model and vector CLI helpers |
| `ingest_recipes.py` | Inherited ingestion utility; not needed for this increment |

## Intent interpretation interface

The page has an **Analyze intent** button using the current English query, and an
**Analyze with search** checkbox (enabled by default). Parsing runs independently
from retrieval so a parser failure does not block manual search. The panel opens
when analysis starts and shows explicit loading, success, clarification and error
states. Editing the query clears stale interpretation and ignores late responses.
An identical completed request can be reused until the query/context changes;
clicking Analyze intent explicitly requests a fresh model call.

The interface reuses `../model/jev_test.py` and `../model/intent_schema.py` directly
through `intent_service.py`. Those source files and their seven-route taxonomy
are unchanged; there is no separately maintained prompt copy. The API performs
candidate preparation, Jev evaluation, answer/probability validation, the existing
`interpret`/`assemble` steps, and Pydantic output validation. Credentials remain
server-side using the existing `AI_GATEWAY_API_KEY` override/fallback configuration.
Real analysis calls the existing AI Gateway endpoint; no fake model fallback is used.
Four concurrent parses are allowed; the gateway socket timeout is 30 seconds and
the browser gives up at 40 seconds. A browser cancellation cannot stop an already
running gateway call; server admission remains bounded until that call ends.

```json
{
  "query": "I have beef and potatoes. Suggest a quick dinner.",
  "context": {"recipes": [], "selected_recipe_id": null}
}
```

Panel content:

- Primary intent and search subtype; model confidence, threshold, parse time.
- Available/required/excluded ingredients, soft preferences, numeric bounds,
  dietary requirements, meal type and planning details when recognized.
- Explicit labels for recognized-but-not-applied constraints, context-only facts,
  suggestions that need confirmation, and missing filter capabilities.
- Clarification questions, uncertain decisions, missing references and current
  task execution limits. A parser status of `ready` does not mean a meal plan,
  comparison or QA task has been executed.
- Expandable intent probability bars, source/schema versions, request ID and
  validated JSON including raw model answers and candidate information.
- Download JSON for the current interpretation; no automatic disk logging.

The existing `quick -> 30 minutes` rule is retained and disclosed as a **system
default needing confirmation**. It is never displayed as applied. Strict `<`
bounds are preserved separately from inclusive `<=` limits. Available ingredients
remain distinct from mandatory ingredients. Dictionary/regex coverage is limited;
empty fields do not establish that all user requirements have been understood.

Optionally check **Use shown recipes** to send up to 20 current result IDs/names
as reference context. Opening a detail card selects its ID and labels it as the last viewed recipe;
that selection lasts until another card is opened or new results arrive. The diagnostics record the context snapshot sent at submission. Query text
and this optional context are the user data sent to Jev; credentials are never
returned to the frontend or included in the downloadable JSON.

New files: `intent_service.py`, `web/intent-ui.js`, and
`tests/test_intent_service.py`. Styles reuse the existing UI tokens. No frontend
framework or additional runtime dependency is introduced.

### GPT-6 direct UI adapter (2026-09-27)

The intent preview now posts to `/intent/parse/gpt6` using OpenAI Responses API
and `gpt-6-astra`. It shows search text, ingredient roles, numeric operators,
original evidence, spelling corrections, clarification questions and elapsed
parsing time. It does not fabricate probability scores or apply filters.
Nutrition basis and recipe-context resolution are not yet mapped; the context
checkbox is disabled. Legacy Jev API remains for regression tests but is not
called by the page or used as a fallback.

Launch from this directory with `/opt/anaconda3/bin/python run_local.py`.
The launcher inherits OPENAI_API_KEY or asks for hidden input; it never saves
the key. The key must belong to the server process, not just a separate test
terminal. The page is at http://127.0.0.1:8001/.

Validation: 39 unit tests passed, including adapter replay of eight saved real
GPT-6 responses, missing-key, credit-exhaustion and invalid-evidence handling.
Browser replay on a separate temporary service verified spelling/soft preference
and conflict displays. The actual server's missing-key message was verified.
A new live UI model call remains pending a server started with the user's key.
Elasticsearch was unavailable during this UI check; live retrieval was not
re-verified. Existing retrieval regression tests passed.

### Intent model selector (2026-09-28)

The page now offers GPT-6 Astra (OpenAI direct, default) and Jev (AI Gateway).
Both render in the same interpretation panel. Switching model aborts the pending
UI request and invalidates the previous result; Analyze intent submits the same
query to the selected adapter. No automatic fallback occurs. Jev's search text
is explicitly the original query, not generated text; candidate coverage warnings
and model-specific diagnostics remain visible. Jev can use shown recipe context.

39 regression tests passed. Browser switching and error rendering were verified;
the current Jev Gateway call returned HTTP 403 (free-tier access restriction),
so live Jev success is blocked by that provider account. Restart the Python
server to load the added Jev response metadata; frontend also accepts its older
response shape.

### OpenAI low-cost model adapters

Intent model now includes GPT-4.1 nano and GPT-4.1 mini, using the same
OPENAI_API_KEY, extraction schema and preview renderer as GPT-6. Routes are
`/intent/parse/gpt41-nano` and `/intent/parse/gpt41-mini`; the GPT-6 route remains
compatible. Only GPT-6 sends reasoning effort; 4.1 models omit this unsupported
parameter. Responses include requested_model and the provider's returned model.
41 tests pass, including model routing, shared schema, request parameters and
rejection of unknown model names without a network call. These are adapter tests,
not accuracy measurements for the two new models. Restart run_local.py in the
terminal containing your key to load the new backend routes.

## Label filters

`labels` accepts comma-separated labels in the UI or a string array in the API.
Values are trimmed, lowercased and deduplicated. At least one complete label must
match either `recipecategory` or `keywords` (case-insensitive keyword term matching).
This condition is ANDed with existing ingredient/time/calorie filters and shared
by BM25 and vector recall. Empty labels do not constrain results. Labels do not
change ranking, expand synonyms, or automatically map meal/dish types yet.
For example, `soup` does not match `clear soup` without an explicit mapping.
The response includes applied labels in `effective_filters`.

## Hybrid preference reranking

Hybrid now fuses the complete candidate union before reranking and truncating.
Normalized RRF = RRF / ((bm25_boost + vector_boost) / (k + 1)).
Final score = Normalized RRF + preference_lambda * preference_score (default 0.30).
Active positive groups have equal weight and their match fractions are averaged;
the avoid-ingredient match fraction is subtracted. No active group contributes zero.
Ingredient matching uses case-insensitive substrings, consistent with existing filters;
cuisine/meal/dish preferences use complete case-insensitive category/keyword tags.
Missing tags earn no bonus. Healthy scoring is not enabled without configured thresholds.
Lambda zero preserves pure RRF order; ties use original RRF rank.
Responses retain raw RRF scores plus final_score, normalized_rrf, rrf_rank,
preference_score and per-group evidence. Cards show rank changes and contributions.
Intent targets now fill ranking preferences, not hard Labels. Hard Labels remain manual.

## Retrieval query source

A ready recipe_search interpretation fills Query from nonempty dish_name first,
then search_text, then the original request. The UI identifies the source; the
full Search Description remains visible and the retrieval query remains editable.
Ingredient constraints and preferences are transferred independently. The extraction
prompt distinguishes core dish identity from separately requested additions.
# DeepSeek Flash intent parsing

Select **DeepSeek Flash · DeepSeek direct** in the Intent model menu.
The backend route is `POST /intent/parse/deepseek-flash`. It calls
`https://api.deepseek.com/chat/completions` directly with `deepseek-flash`,
thinking disabled, JSON output and a 3500-token output limit.

Set `DEEPSEEK_API_KEY` in the terminal used to launch the backend, then restart
the backend. For zsh, enter the key without displaying it or storing it in shell history:

```zsh
read -s 'DEEPSEEK_API_KEY?DeepSeek API Key: '
export DEEPSEEK_API_KEY
python -m uvicorn recipe_search_api:app --host 127.0.0.1 --port 8001
```

Refresh the browser after restarting. OpenAI credentials are not used for DeepSeek.
The shared business `PROMPT` and `Extraction` schema are unchanged. DeepSeek uses
an additional system message containing the JSON schema because JSON mode alone
does not enforce schema compliance. The same local schema/evidence/unit checks
run before presentation. Invalid or truncated output is blocked and shown through
the existing diagnostics UI. Results record `provider`, `requested_model`, actual
`model`, `prompt_version`, `output_mode`, `thinking_mode`, and
`format_instruction_version`; account for the different output mechanism in evaluations.
Adapter tests use mocked responses; a live call requires the configured DeepSeek key.
