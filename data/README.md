# Data (source input)

This folder is the default source-data location (`DATA_DIR` empty in `.env`). Its
contents are git-ignored; only this README is tracked. It holds only input data:

```text
data/
└── recipes.parquet      # source recipes (required for offline steps)
```

Everything generated from it (vocabulary, extraction JSONL, image mapping,
caches, outputs) goes to [`var/`](../var/README.md) instead. Older layouts that
keep generated files in `DATA_DIR/derived/` are still read.

`recipes.parquet` is the `recipes` table (522,517 recipes) of the Food.com dataset
[Food.com Recipes and Reviews](https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews),
used under its own terms. `recipe-ingest` can also read it from a URL with `--source-url`.

To use data that already lives elsewhere, either set `DATA_DIR`, or link it in:

```bash
ln -s /absolute/path/to/recipes.parquet data/recipes.parquet
```

Symlinks pointing outside the repository do not resolve inside Docker; for
containers, set `DATA_DIR` to the absolute folder instead.

The running app reads recipe records from ES. The image mapping is optional:
without it, source photos still work and missing photos use the shipped SVG
category icons. No startup, test or CI step imports data or writes to ES. See
[docs/data-pipeline.md](../docs/data-pipeline.md) for the offline steps.
