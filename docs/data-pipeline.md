# Data pipeline: from Parquet to Elasticsearch

This document describes every step that writes recipe data, which store each step
writes, and the fields the running app depends on. The app itself never writes
recipe documents; all writes below are explicit offline commands.

```text
DATA_DIR/recipes.parquet  (Food.com, 522,517 recipes)
   │
   ├─⓪  build_bm25_vocabulary ─► src/recipe_search/config/bm25_vocabulary.json   (generated, git-ignored)
   │                                  │  required by ②a and by the app
   ├─①  recipe-ingest ─────────────────┼──────────────────► ES index (ES_INDEX, default recipes_clean)
   │       clean · parse · time backfill · tag normalize · BGE embedding     full documents
   │                                  ▼
   ├─②a scripts/extraction/extract_ingredients.py ─► DATA_DIR/derived/extract_ingredients_rule_v1.jsonl
   │   ②b update_extracted_ingredients ────────────► ES partial update: extract_* fields
   │
   ├─③  refresh_extracted_vocabulary (reads ES) ──► adds extract_ingredients terms to the vocabulary
   │
   ├─④  refresh_tags (only for indexes built before tag normalization) ─► ES partial update
   │
   └─⑤  build_image_fallback ─► DATA_DIR/derived/image_fallback_v2.{jsonl,sqlite}
```

> **Generate the vocabulary first.** Step ⓪ must run before the extraction
> script (②a) and before starting the app. The file is built from your data, is
> listed in `.gitignore` and is never committed. Unit tests use a small fixture
> instead (`tests/unit/fixtures/bm25_vocabulary.json`).

| Step | Command | Writes to | Write type |
|---|---|---|---|
| ⓪ Vocabulary | `uv run python scripts/build_bm25_vocabulary.py` | `src/recipe_search/config/bm25_vocabulary.json` | local JSON, from Parquet |
| ① Ingest | `uv run recipe-ingest --with-embeddings` | ES | `index` (whole document, `_id = recipeid`); deletes the index only with `--recreate` |
| ②a Extraction | `uv run python scripts/extraction/extract_ingredients.py` | `DATA_DIR/derived` | local JSONL + stats |
| ②b Load extraction | `uv run python -m recipe_search.ingest.update_extracted_ingredients` | ES | `update` (partial `doc`) + additive mapping |
| ③ Vocabulary refresh | `uv run python scripts/refresh_extracted_vocabulary.py` | vocabulary file | reads ES only |
| ④ Tag normalization | `uv run python scripts/refresh_tags.py` | ES | `update` with optimistic concurrency, after backup |
| ⑤ Image fallback | `uv run python scripts/build_image_fallback.py` | `DATA_DIR/derived` | local JSONL + SQLite |

All commands read `ES_URL`, `ES_USERNAME`, `ES_PASSWORD`, `ES_CA_CERTS`, `ES_INDEX`,
`EMBEDDING_MODEL`, `DATA_DIR`, `OUTPUT_DIR` and `BM25_VOCABULARY` from the
environment or `.env`. Take an ES snapshot before any step that writes ES.

A complete first build, in order:

```bash
uv run python scripts/build_bm25_vocabulary.py                       # ⓪
uv run recipe-ingest --recreate --with-embeddings                    # ① (new or rebuilt index)
uv run python scripts/extraction/extract_ingredients.py             # ②a
uv run python -m recipe_search.ingest.update_extracted_ingredients   # ②b
uv run python scripts/refresh_extracted_vocabulary.py                # ③
uv run python scripts/build_image_fallback.py prepare                # ⑤ (then match/finalize)
```

## ⓪ Matching vocabulary (generated, not versioned)

The app reads the vocabulary for word-form and ingredient matching, and the
extraction rules (②a) use its `ingredients` field as their term list.

```bash
uv run python scripts/build_bm25_vocabulary.py   # ingredients, ingredients_raw, keywords, recipecategory
```

- Output goes straight to the path the app reads:
  `src/recipe_search/config/bm25_vocabulary.json`. Set `BM25_VOCABULARY` to an
  absolute path to use another location; both scripts and the app follow it.
- The file is git-ignored. A missing file stops the app's matching with an error
  explaining how to build it.
- The Docker image and a locally built wheel include the file when it exists at
  build time. Build the vocabulary before `docker compose build`.
- Rebuilding keeps any `extract_ingredients` terms already in the file. Restart
  the app after changing it.

## ① Ingest recipes (`recipe-ingest`)

Source: `--source-url` (local path or URL), default `DATA_DIR/recipes.parquet`.
Code: `src/recipe_search/ingest/ingest_recipes.py`.

Processing per row:

1. **Clean**: `NA`, `nan`, `null`, empty strings → missing; missing fields are dropped.
2. **Parse R vectors**: strings like `c("a", "b")` → lists (images, keywords,
   ingredient parts/quantities, instructions). Quantities keep empty slots so they
   stay aligned with ingredient positions.
3. **Durations**: ISO 8601 (`PT1H30M`) → integer minutes.
4. **Time backfill**: `cook = total − prep`; `prep = total − cook`; a `< N mins` tag
   fills missing total, cook and prep with N.
5. **Derived text**: `searchable_text` and `embedding_text` are built from the
   *original* tags; then `keywords` and `recipecategory` are normalized
   (`matching/tag_normalization.py`).
6. **Embedding** (only with `--with-embeddings`): `embedding_text` →
   `BAAI/bge-base-en-v1.5`, max 512 tokens, L2-normalized, 768 dims → `content_vector`.
7. **Bulk index**: batches of `--bulk-chunk-size` (1000) with retries; final refresh.

Index lifecycle:

| Invocation | Index behavior |
|---|---|
| default (no `--recreate`) | **keeps** an existing index; creates it with the full mapping only if missing; adds `embedding_text`/`content_vector` mapping if absent |
| `--recreate` | **deletes the index and creates it again** before importing (cannot be combined with `--offset` or recipe ids) |
| `--offset N` | resume a stopped import from source row N |
| `--recipe-ids …` / `--recipe-ids-file` | re-index only those recipes |

`--keep-index` is still accepted for old commands but no longer does anything.

```bash
# New index, or a deliberate full rebuild (slow: embeds 522k recipes)
uv run recipe-ingest --recreate --with-embeddings

# Re-import into the existing index (documents with the same id are overwritten)
uv run recipe-ingest --with-embeddings

# Resume after an interruption at source row 200000
uv run recipe-ingest --with-embeddings --offset 200000

# Re-index specific recipes without touching the rest
uv run recipe-ingest --with-embeddings --recipe-ids 38 39 40

# Small trial into a separate index
uv run recipe-ingest --index recipes_trial --limit 500 --with-embeddings
```

Caveats:

- `index` replaces the **whole document**. Re-ingesting a recipe removes fields
  added by later steps (`extract_*`), and without `--with-embeddings` also removes
  its `content_vector`. Always pass `--with-embeddings`, and rerun step ②b afterwards.
- Re-importing into a kept index does not remove documents whose recipes have
  disappeared from the source; use `--recreate` for an exact rebuild.

## ② Instruction-extracted ingredients

**②a Extraction** (rule-based, no LLM, no ES writes). Code: `scripts/extraction/`
(`rules.py` matching rules, `supplement.py` curated names, `extract_ingredients.py`
runner; see its [README](../scripts/extraction/README.md)). Requires the vocabulary
from step ⓪.

```bash
uv run python scripts/extraction/extract_ingredients.py                     # all recipes
uv run python scripts/extraction/extract_ingredients.py \
  --start 0 --end 1000 --output /abs/path/extract_trial.jsonl              # trial on 1000 rows
uv run python scripts/extraction/extract_ingredients.py --force             # replace existing output
```

How a term is found:

1. Vocabulary `ingredients` names of one or two words, minus stop words (water,
   salt, sauce, colors, …) and kitchen items (foil, parchment paper, …), plus the
   curated supplement (cooking spray, orange juice, chicken stock, …).
2. Instructions are split at punctuation, words are singularized and matched as
   1–2-grams. A match followed by an equipment word (pan, dish, maker, …) is skipped.
3. A term is dropped when the recipe's ingredient list already covers it (exact
   phrase, all of its words, or all of its food words).
4. The first sentence mentioning the term becomes its evidence. `hedged` marks
   sentences containing serve, garnish, optional, if desired, substitute, ….

Output: `DATA_DIR/derived/extract_ingredients_rule_v1.jsonl` (one line per
recipe) and `extract_ingredients_rule_v1_stats.json`. An existing output is only
replaced with `--force`. Example record:

```json
{"recipeid": "38", "extract_ingredients": ["berry"],
 "extract_evidence": [{"ingredient": "berry", "text": "Toss 2 cups berries with sugar.", "hedged": false}],
 "ingredient_parts_count": 4, "ingredient_quantities_count": 4,
 "ingredient_list_incomplete": false, "extraction_version": "rule-v1"}
```

This runner reproduces the original 2026-10-23 output byte for byte (checked on
sample row ranges against the existing JSONL).

**②b Load into ES**. Code: `src/recipe_search/ingest/update_extracted_ingredients.py`.

1. Adds the mapping for `extract_ingredients`, `extract_ingredients_firm`,
   `extract_evidence` and `extraction_version` (existing fields untouched).
2. Classifies each evidence sentence's `usage` (`matching/ingredient_sources.py`).
3. `extract_ingredients_firm` = extracted terms with at least one `preparation` usage.
4. Sends partial `update` requests in batches; failures print the `--offset` to resume from.

```bash
M="uv run python -m recipe_search.ingest.update_extracted_ingredients"
$M --dry-run --limit 1000      # validate only, no ES connection
$M --limit 1000                # pilot on the first 1000 lines
$M                             # full run (resume with --offset N if stopped)
```

The update targets existing documents only; recipes missing from the index fail
and stop the batch.

## ③ Refresh extracted terms in the vocabulary (reads ES only)

```bash
uv run python scripts/refresh_extracted_vocabulary.py
```

Collects all `extract_ingredients` values from ES and writes them into the
vocabulary's `extract_ingredients` field. Run it after ②b, then restart the app.
It requires the file from step ⓪ to exist.

## ④ Tag normalization for older indexes (`scripts/refresh_tags.py`)

Ingest already normalizes tags. This script is only for an index built before
that, and it changes **only** `recipecategory` and `keywords`.

```bash
uv run python scripts/refresh_tags.py prepare --run-dir /abs/path/tag-run   # read-only backup + manifest
uv run python scripts/refresh_tags.py apply   --run-dir /abs/path/tag-run   # writes, with if_seq_no/if_primary_term
uv run python scripts/refresh_tags.py resume  --run-dir /abs/path/tag-run   # reconcile after an interruption
```

`prepare` saves `original-tags.jsonl.gz` and `manifest.json` (index UUID,
normalizer version, checksum). `apply` refuses to run if the index, the
normalizer or the backup has changed, holds a writer lock, verifies every
document afterwards and writes a report.

## ⑤ Image fallback mapping (local SQLite, no ES writes)

For recipes without photos, finds a similar recipe that has one (L1 same name →
L2 same head phrase → L3 same dish form + main ingredient, score ≥ 0.35).

```bash
uv run python scripts/build_image_fallback.py prepare           # cache under OUTPUT_DIR/image-fallback-cache; prints target count
uv run python scripts/build_image_fallback.py match 0 120000    # repeat for further ranges up to the target count
uv run python scripts/build_image_fallback.py finalize          # writes DATA_DIR/derived/image_fallback_v2.{jsonl,sqlite}
```

The app reads the SQLite file through `RECIPE_IMAGE_FALLBACK_DB`, defaulting to
`DATA_DIR/derived/image_fallback_v2.sqlite`. Without it, SVG category icons are shown.

## Field reference (ES document)

`_id` = `recipeid`. Source columns are from the Food.com Parquet.

### Identity and display

| Field | ES type | Source | Notes |
|---|---|---|---|
| `recipeid` | keyword | `recipeid` | string; also the document `_id` |
| `name` | text + `name.keyword` (lowercase) | `name` | BM25 boost ^5 |
| `description` | text | `description` | BM25 ^2 |
| `image_urls` | keyword[] | `images` | empty → image fallback ⑤ |
| `aggregatedrating`, `reviewcount` | float, integer | same | rating used in preference reranking; review count picks image donors |
| `recipeservings`, `recipeyield` | float, keyword | same | display |

### Ingredients and tags

| Field | ES type | Source | Notes |
|---|---|---|---|
| `ingredients` | keyword[] (lowercase) | `recipeingredientparts` | include/exclude filters, BM25 ^2 |
| `ingredient_quantities` | keyword[] | `recipeingredientquantities` | aligned with `ingredients`; empty slots kept |
| `keywords` | keyword[] (lowercase) | `keywords`, normalized | tag filters, BM25 ^3 |
| `recipecategory` | keyword[] (lowercase) | `recipecategory`, normalized | tag/dish-type evidence together with `keywords` |
| `extract_ingredients` | keyword[] | step ② | instruction mentions not in `ingredients`; evidence only |
| `extract_ingredients_firm` | keyword[] | step ② | preparation-usage subset; BM25 ^2 and eligibility |
| `extract_evidence` | object (not indexed) | step ② | `{ingredient, text, hedged, usage}` for check/generation |
| `extraction_version` | keyword | step ② | e.g. `rule-v1-usage-v1` |

### Time and nutrition

| Field | ES type | Source | Notes |
|---|---|---|---|
| `total_time_minutes` | integer | `totaltime` + backfill | time filters and relaxation |
| `cook_time_minutes`, `prep_time_minutes` | integer | `cooktime`, `preptime` + backfill | |
| `calories` | float | `calories` | per serving; calorie filters and relaxation |
| `fatcontent`, `saturatedfatcontent`, `cholesterolcontent`, `sodiumcontent`, `carbohydratecontent`, `fibercontent`, `sugarcontent`, `proteincontent` | float | same | per serving |

### Text and vectors

| Field | ES type | Built from | Used by |
|---|---|---|---|
| `instructions` | text[] | `recipeinstructions` | evidence/highlights, generation |
| `instructions_text` | text | instructions joined by newlines | |
| `searchable_text` | text | name, description, category, keywords, ingredients, instructions | BM25 catch-all field |
| `embedding_text` | text | `title: … / category: … / description: … / keywords: … / ingredients: … / instructions: …` | input to the embedding |
| `content_vector` | dense_vector (768, cosine, indexed) | BGE embedding of `embedding_text` | Vector branch (kNN) |

The BM25 branch queries `name^5, keywords^3, ingredients^2,
extract_ingredients_firm^2, description^2, searchable_text`
(`api/search.py`). The Vector branch runs kNN on `content_vector` with the
same filters.

If `EMBEDDING_MODEL` is changed, `content_vector` must be fully rebuilt (step ①
with `--recreate --with-embeddings`), because query and document vectors must come from the
same model.
