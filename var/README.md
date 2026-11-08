# var/ — generated files (git-ignored)

Everything the project generates is written here; only this README is tracked.
Delete any of it and regenerate with the commands in
[docs/data-pipeline.md](../docs/data-pipeline.md). Set `WORK_DIR` in `.env` to use
another location.

```text
var/
├── bm25_vocabulary.json        # matching vocabulary (scripts/build_bm25_vocabulary.py)
├── derived/                    # extraction JSONL + stats, image_fallback_v2.sqlite (photo mapping)
├── cache/
│   └── huggingface/            # embedding model cache (HF_HOME), downloaded on first use
├── outputs/                    # diagnostics, evaluation runs, benchmarks, tag-refresh backups (OUTPUT_DIR)
└── screenshots/                # browser-test screenshots
```

Source data (`recipes.parquet`) is not generated and lives in `DATA_DIR`
(default `data/`). For reads, `derived/` files are also found in the older
`DATA_DIR/derived/` location.
