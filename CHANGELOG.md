# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/) from v1.4.0 on.

Tags `v1.0`–`v1.3` are sanitized reconstructions of earlier prototype folders
(see [Historical versions](README.md#historical-versions)); their dates below are the original prototype
dates, while the Git commit/tag timestamps are migration dates (2026-11-05).

## [Unreleased]

Repository migration and engineering work on `main` after the 1.3 snapshot.

### Added
- Installable package `almost-delicious` under `src/recipe_search/`
  (`api`, `retrieval`, `matching`, `ranking`, `llm`, `ingest`, `presentation`),
  with CLI entry points `almost-delicious`, `recipe-ingest` and `recipe-search`.
- Central environment configuration (`settings.py`, `.env.example`); secrets are
  read only from the environment or an ignored `.env`.
- Locked dependencies (`uv.lock`), multi-stage `Dockerfile`, `docker-compose.yml`
  and an opt-in local TLS Elasticsearch stack (`infra/compose.local-es.yml`).
- GitHub Actions CI: Ruff, unit tests, history secret scan, wheel install check,
  Playwright browser tests and container build.
- `scripts/scan_secrets.py`, `SECURITY.md` policy, migration guides and an MIT `LICENSE`.
- `scripts/extraction/`: the rule-v1 instruction-ingredient extraction, moved into
  the repository with a documented runner; output is identical to the original run.
- `docs/data-pipeline.md`: the full data-side write process and ES field reference.

### Changed
- **`recipe-ingest` no longer deletes the index by default.** Pass `--recreate`
  to rebuild it; `--keep-index` is now a no-op.
- The matching vocabulary is generated directly to
  `src/recipe_search/config/bm25_vocabulary.json` (or `BM25_VOCABULARY`) and is no
  longer committed; unit tests use a small fixture.
- `SECURITY.md` is now a vulnerability-reporting policy; `HISTORY.md` merged into
  the README's Historical versions section.
- `PRODUCT.md` and `DESIGN.md` (local impeccable design context) are no longer tracked.
- Process notes (review briefs, stage reviews, proposals, the inherited 1.2 README,
  migration guides) and all diagram files moved out of the repository (diagrams
  are maintained in an online drawing tool). `docs/` holds the retrieval flow,
  multi-direction relaxation and data pipeline.
- Tests split into `tests/unit` and `tests/browser`; imports normalized with Ruff.
- Default local port unified to 8001 across all versions.
- Generated-image ignore rules scoped to evidence folders instead of all PNG/JPG.

### Fixed
- Bounded ingredient emphasis; named-dish `sole` vs `and/or` emphasis now distinct
  (known failure retained on the `v1.3` compatibility tag).
- Image-mapping SQLite connections are closed explicitly.

### Security
- Hardcoded Elasticsearch password and AI Gateway key removed from every
  reconstructed snapshot and from all published history.

## [1.3] - 2026-10-29

### Added
- Multi-direction recall relaxation: below 10 strict candidates, up to three
  non-overlapping relaxation directions, each with at least three matches.
- Single-`msearch` BM25 relaxation and filtered vector relaxation reusing the
  strict query vector, with a shared 1.5 s relaxation budget and partial results.
- Near-miss groups based on actual deviations, with per-group explanations in
  generation; formal recommendations use only fully qualifying recipes.
- Relaxation flow view with per-branch timings, plan statistics and DSL.

## [1.2] - 2026-10-15

### Added
- Unified hard-condition relaxation replacing the BM25-only required fallback,
  with explicit disclosure when a sole required ingredient is waived.
- Direct OpenAI and DeepSeek intent parsing (`recipe-extraction-v4`) alongside JEV,
  classifying ingredients as `specific` or `category` with roles and evidence.
- Recipe qualification checks and grounded content generation with batch recovery.
- Preference ranking, recommendation de-duplication and image fallback mapping.
- Progressive workflow UI and Playwright browser regression tests.

## [1.1] - 2026-09-24

### Added
- Application-level weighted Reciprocal Rank Fusion: independent BM25 and vector
  requests with deterministic tie-breaking.
- JEV intent interpretation endpoint with schema validation.
- Per-branch, fusion and parse timings; tag normalization and expansion.
- First unit test suite and offline evaluation scripts.

## [1.0] - 2026-09-16

### Added
- FastAPI recipe search over Elasticsearch with BM25, vector (`BAAI/bge-base-en-v1.5`)
  and ES-native hybrid modes.
- Ingredient include/exclude, total-time and calorie filters.
- `/health`, `/recipes/search`, `/recipes/{recipe_id}` and streaming search.
- Parquet ingestion script and a compact comparison web UI.

[Unreleased]: https://github.com/FooIisher/almost-delicious/compare/v1.3...main
[1.3]: https://github.com/FooIisher/almost-delicious/compare/v1.2...v1.3
[1.2]: https://github.com/FooIisher/almost-delicious/compare/v1.1...v1.2
[1.1]: https://github.com/FooIisher/almost-delicious/compare/v1.0...v1.1
[1.0]: https://github.com/FooIisher/almost-delicious/releases/tag/v1.0
