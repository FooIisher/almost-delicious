# Almost Delicious

A research prototype for recipe search: understand a request, retrieve recipes,
check requirements, and generate grounded recommendations. BM25, Vector and
Hybrid workbenches expose actual queries, rankings and relaxation tradeoffs.

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

The CLI reads APP_HOST/APP_PORT; explicit uvicorn flags take precedence. For a
launch from another directory, set ENV_FILE to the absolute path of your .env.
Credentials may also be supplied through process environment variables, which
have precedence over .env. There are no built-in passwords.

### Data side: writing recipes to Elasticsearch

Starting the app only reads ES. Building or updating the index is a separate,
explicit offline process. Full details, flags and the field reference are in
[docs/data-pipeline.md](docs/data-pipeline.md).

> **Generate the matching vocabulary before anything else.** Both the app and
> the extraction script need it. It is built from your data, is git-ignored
> and is never committed:
>
> ```bash
> uv run python scripts/build_bm25_vocabulary.py   # writes src/recipe_search/config/bm25_vocabulary.json
> ```

| Step | Command | Writes |
|---|---|---|
| 0. Vocabulary | `uv run python scripts/build_bm25_vocabulary.py` | local `config/bm25_vocabulary.json` |
| 1. Ingest recipes | `uv run recipe-ingest --with-embeddings` (add `--recreate` to rebuild) | ES: whole documents, `_id = recipeid` |
| 2a. Extract instruction ingredients | `uv run python scripts/extraction/extract_ingredients.py` | `DATA_DIR/derived/extract_ingredients_rule_v1.jsonl` |
| 2b. Load extraction | `uv run python -m recipe_search.ingest.update_extracted_ingredients` | ES: partial update of `extract_*` |
| 3. Refresh vocabulary from ES | `uv run python scripts/refresh_extracted_vocabulary.py` | local vocabulary (`extract_ingredients`) |
| 4. Tag normalization (old indexes only) | `uv run python scripts/refresh_tags.py prepare\|apply\|resume --run-dir DIR` | ES: `keywords`, `recipecategory` |
| 5. Image fallback | `uv run python scripts/build_image_fallback.py prepare\|match\|finalize` | `DATA_DIR/derived/*.sqlite` |

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

Set DATA_DIR to the absolute external data directory (the original project data
may remain in place). The Parquet dataset, JSONL outputs, SQLite mapping and model
cache are not repository assets. See [data preparation](data/README.md). Missing
image mappings degrade to shipped SVG icons; the old raster placeholder set is
not required by the current UI and is not tracked. Optional offline commands:

```bash
uv run recipe-ingest --help
uv run recipe-search --help
uv run python scripts/build_image_fallback.py prepare
```

The latter requires DATA_DIR and writes derived files only when explicitly run.
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
locked Playwright Chromium by default. Generated screenshots/logs stay outside
Git. Real model evaluations and retrieval benchmarks are separate opt-in scripts;
they require explicit case inputs/output paths and may incur provider costs.

## Containers

The default Compose runs only the app and connects to an existing ES. Set ES_URL
to a container-reachable host (for local Docker, https://host.docker.internal:19200)
and CERTS_DIR to an absolute directory containing its public CA as ca.crt.

```bash
docker compose build
docker compose up -d app
```

DATA_DIR is mounted read-only. Model cache and generated diagnostics use named
volumes. The application image uses Python 3.12 and Linux CPU PyTorch; it includes
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

## Layout and history

- src/recipe_search: API, retrieval, matching, ranking, LLM/JEV, ingest and presentation.
- Package config/ and web/: versioned runtime resources.
- tests/unit and tests/browser: backend and browser regressions.
- scripts and experiments: explicit offline/evaluation tools.
- docs: architecture and migration notes; thesis documents stay outside this repo.

Tags v1.0–v1.3 are sanitized reconstructions of directory snapshots, not original
commit history. Their timestamps are migration timestamps. Shared JEV files use
the available shared copy; external legacy images/data are not included. Later
main commits isolate the baseline fix, packaging, formatting and deployment work.

Before publication, follow the [publication checklist](docs/migration/publication.md).
Security reports: see [SECURITY.md](SECURITY.md).

## License

The code is released under the [MIT License](LICENSE). The recipe data
(Food.com recipes via Kaggle) is not part of this repository and remains under
its own terms; see [data/README.md](data/README.md).
