# Recipe Search Prototype 1.3

A separate runnable baseline for multi-direction recall relaxation. Prototype 1.2 is unchanged.

## Start

```bash
cd "/path/to/thesis/project/prototype-1.3"
python run_local.py
```

Open http://127.0.0.1:8003 (API docs: http://127.0.0.1:8003/docs). Use the same server-terminal credentials as 1.2. Both versions can run side by side. The index, embedding model and source data are shared; no reindex or data write is needed.

## New behavior

- Strict BM25 / Vector recall remains 500 per branch, RRF Top 100.
- Below 10 unique strict candidates, choose up to three non-overlapping relaxation directions, each with at least three filter-range matches.
- BM25 uses one msearch, five candidates per direction. Vector reuses the strict vector, combines filters with OR (k=15, num_candidates=100), and permits at most two bounded quota refills. Small plans use direct filters rather than kNN.
- One 1.5-second relaxation budget; keep completed results on partial failure.
- Original qualification rules remain active. Actual deviations define near-miss groups, with two selected alternatives per group by default. Formal recommendations only use pass recipes.
- Flow above results shows the selected directions and separate branch timings/counts. The icon opens plan statistics, actual retention, errors and DSL. Generation explains each group separately and keeps source recipes unchanged.
- Research settings retain single-plan v1 and expose multi-plan limits/quotas.

## Documentation

- [Implementation, information flow and configuration](docs/v1.3/multi-relaxation.md)
- [User proposal including v2](docs/v1.3/relaxation-proposal.md)
- [Inherited 1.2 notes — historical baseline, not the current startup instructions](docs/v1.3/README-1.2-inherited.md)
- [Mocked regression evidence](verification/multi-relaxation-v2-20261031/README.md)

## Verification

```bash
RECIPE_WARMUP=0 python -m unittest discover -s tests
```

Browser tests use local Playwright and intercepted ES/model responses. Real retrieval/model quality, p50/p95 and paid cost evaluation are separate; no speedup is promised.

The retrieval-only benchmark now compares `single`, `multi-separate` and `multi-combined` on a saved request:

```bash
python scripts/benchmark_retrieval_depth.py \
  --snapshot /absolute/path/to/request.json --depths 500 --repeats 5 \
  --output verification/relaxation-benchmark.json
```
