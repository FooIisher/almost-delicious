# Almost Delicious

A research prototype for recipe search: understand a request, retrieve recipes,
check requirements, and generate grounded recommendations. Hybrid retrieval (BM25 +
vector kNN, fused with RRF) runs on **Elasticsearch**. BM25, Vector and Hybrid
workbenches expose actual queries, rankings and relaxation tradeoffs.

Data: the public [Food.com Recipes and Reviews](https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews)
dataset on Kaggle, about 520,000 recipes (522,517). It is not included in this
repository; see [data/README.md](data/README.md).

## Local development

Requires Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/). No API key is
required for the mocked tests. Live intent/check/generation requires a provider key.

```bash
uv sync --frozen
cp .env.example .env
# Edit .env locally; never commit it.
uv run almost-delicious
```

Open http://127.0.0.1:8001. The equivalent fixed-address command is:

```bash
uv run uvicorn recipe_search.api.app:app --host 127.0.0.1 --port 8001
```

The CLI reads APP_HOST/APP_PORT; explicit uvicorn flags take precedence. The
repository's `.env` is used from any working directory; set ENV_FILE to use a
different file.
Credentials may also be supplied through process environment variables, which
have precedence over .env. There are no built-in passwords.

### Data side: writing recipes to Elasticsearch

Starting the app only reads ES. Building or updating the index is a separate,
explicit offline process. Full details, flags and the field reference are in
[docs/data-pipeline.md](docs/data-pipeline.md).

- **Input**: place `recipes.parquet` in `data/` (the default when `DATA_DIR` is
  empty), or set `DATA_DIR` in `.env` to the folder that already holds it. See
  [data/README.md](data/README.md).
- **Generated files**: everything the steps below produce goes to `var/`
  (`WORK_DIR`): the vocabulary, `derived/`, `cache/`, `outputs/` and test
  screenshots. Both folders are git-ignored except their README; see
  [var/README.md](var/README.md).

> **Generate the matching vocabulary before anything else.** Both the app and
> the extraction script need it. It is built from your data, is git-ignored
> and is never committed:
>
> ```bash
> uv run python scripts/build_bm25_vocabulary.py   # writes var/bm25_vocabulary.json
> ```

| Step | Command | Writes |
|---|---|---|
| 0. Vocabulary | `uv run python scripts/build_bm25_vocabulary.py` | `var/bm25_vocabulary.json` |
| 1. Ingest recipes | `uv run recipe-ingest --with-embeddings` (add `--recreate` to rebuild) | ES: whole documents, `_id = recipeid` |
| 2a. Extract instruction ingredients | `uv run python scripts/extraction/extract_ingredients.py` | `var/derived/extract_ingredients_rule_v1.jsonl` |
| 2b. Load extraction | `uv run python -m recipe_search.ingest.update_extracted_ingredients` | ES: partial update of `extract_*` |
| 3. Refresh vocabulary from ES | `uv run python scripts/refresh_extracted_vocabulary.py` | local vocabulary (`extract_ingredients`) |
| 4. Tag normalization (old indexes only) | `uv run python scripts/refresh_tags.py prepare`, then `apply` (or `resume`) | ES: `keywords`, `recipecategory` |
| 5. Image fallback | `uv run python scripts/build_image_fallback.py` | `var/derived/image_fallback_v2.sqlite` |

Step 1 reads `DATA_DIR/recipes.parquet` and, for each recipe:

- cleans missing values and parses R-style lists;
- converts ISO durations to minutes and backfills missing time fields;
- normalizes tags;
- builds `searchable_text` (BM25) and `embedding_text`;
- embeds `embedding_text` with `EMBEDDING_MODEL` into a 768-dim `content_vector`;
- bulk-indexes the result.

Step 2a finds ingredients that instructions mention but the ingredient list
omits (rule-based, no LLM). See [scripts/extraction](scripts/extraction/README.md).

Main document fields:

- **Identity/display**: `recipeid`, `name`, `description`, `image_urls`,
  `aggregatedrating`, `reviewcount`.
- **Ingredients/tags**: `ingredients`, `ingredient_quantities`, `keywords`,
  `recipecategory`, plus `extract_ingredients`, `extract_ingredients_firm` and
  `extract_evidence` from step 2.
- **Filters**: `total_time_minutes`, `cook_time_minutes`, `prep_time_minutes`,
  `calories` and per-serving nutrition.
- **Retrieval**: `searchable_text`, `embedding_text`, `content_vector`.

> **Before writing ES, take a snapshot.**
> - `recipe-ingest` keeps an existing index. Only `--recreate` deletes it and
>   builds it again.
> - Re-indexing a recipe replaces the whole document, so run step 2b again
>   afterwards and always pass `--with-embeddings`.
> - Use `--index recipes_trial --limit 500` for trials.

## Existing Elasticsearch and external data

Set ES_URL, ES_USERNAME, ES_PASSWORD and, for a private CA, absolute ES_CA_CERTS.
TLS verification stays enabled. Keep the existing index; startup never ingests
recipes or migrates index data. Set RECIPE_WARMUP=false to skip local embedding/ES
warmup. Provider calls remain explicit UI actions, never startup tasks.

Leave DATA_DIR empty to use the repository's data/ folder, or set it to an absolute
external data directory (the original project data may remain in place).
Generated JSONL/SQLite files go to var/derived. The Parquet dataset, generated
files and model cache are not repository assets. See [data preparation](data/README.md). Missing
image mappings degrade to shipped SVG icons; the old raster placeholder set is
not required by the current UI and is not tracked. Optional offline commands:

```bash
uv run recipe-ingest --help
uv run recipe-search --help
uv run python scripts/build_image_fallback.py
```

The latter reads recipes.parquet and writes var/derived only when explicitly run.
Tag/extraction update and ingest commands intentionally write ES: review their
help and back up the index before a deliberate data operation.

## Tests and formatting

Unit tests use the small fixture `tests/unit/fixtures/bm25_vocabulary.json`, so
they do not need the generated vocabulary or any data:

```bash
RECIPE_WARMUP=0 uv run python -m unittest discover -s tests/unit
uv run ruff check src scripts experiments tests/unit
uv run ruff format --check src scripts experiments tests/unit
uv run python scripts/scan_secrets.py --history
uv build
```

Browser tests require Node 24 and npm:

```bash
npm ci
npx playwright install chromium
npm run test:ui-unit
npm run test:browser
```

They intercept retrieval/provider traffic and do not spend model credits. A local
browser executable may be selected through PLAYWRIGHT_EXECUTABLE_PATH; CI uses the
locked Playwright Chromium by default. Screenshots go to `var/screenshots/`,
outside Git. Real model evaluations and retrieval benchmarks
(`run_rq1_intent.py`, `evaluate_unified.py`, `benchmark_retrieval_depth.py`) are
separate opt-in scripts; they require explicit case inputs, may incur provider
costs, and by default write a new timestamped folder or file under `var/outputs/`.

## Containers

The default Compose runs only the app and connects to an existing ES. Set ES_URL
to a container-reachable host (for local Docker, https://host.docker.internal:19200)
and CERTS_DIR to an absolute directory containing its public CA as ca.crt.

```bash
docker compose build
docker compose up -d app
```

DATA_DIR and var/ (as WORK_DIR=/work) are mounted read-only; build the vocabulary
on the host first. Model cache and generated diagnostics use named volumes. The application image uses Python 3.12 and Linux CPU PyTorch; it includes
code/config/static assets, not keys, recipes, models or SQLite databases.

A separate TLS/authenticated ES stack is an explicit opt-in:

```bash
docker compose -f docker-compose.yml -f infra/compose.local-es.yml up -d
```

Set a new ES_PASSWORD first. This creates separate volumes and binds ES at local
port 19201, avoiding the existing 19200 service. It does not import an index or
change any existing cluster. The readiness endpoint /health checks ES; the
container liveness check uses / so missing ES does not conceal an app startup.
See [deployment notes](infra/README.md).

## Layout

- `src/recipe_search`: API, retrieval, matching, ranking, LLM/JEV, ingest and presentation;
  `config/` and `web/` are packaged runtime resources.
- `tests/unit`, `tests/browser`: backend and browser regressions.
- `scripts`, `scripts/extraction`, `experiments`: explicit offline and evaluation tools.
- `docs`: [retrieval flow](docs/retrieval-flow.md),
  [multi-direction relaxation](docs/multi-relaxation.md) and
  [data pipeline](docs/data-pipeline.md).

## Historical versions

Tags `v1.0`–`v1.3` are sanitized reconstructions of the earlier prototype folders,
not original development history; their commit dates are migration dates. Each
tag includes only compatibility fixes so it can run on its own. External data and
legacy images are not included, and the matching vocabulary must be supplied.

```bash
git switch --detach v1.2      # stop the server and commit your work first
uv sync --frozen
uv run python run_local.py --port 8001
git switch main && uv sync --frozen   # back to the current version
```

Security reports: see [SECURITY.md](SECURITY.md).

## License

The code is released under the [MIT License](LICENSE). The recipe data
([Food.com Recipes and Reviews](https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews) on Kaggle) is not part of this repository and remains under
its own terms; see [data/README.md](data/README.md).
