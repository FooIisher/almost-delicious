# External data

This folder intentionally contains no recipes, generated indexes or image mappings.
Set DATA_DIR to the absolute path of your existing data directory. For the current
workspace that directory remains outside this repository. A source Parquet should
be supplied by its owner/licensed dataset provider; do not commit it here.

Expected optional files:
- recipes.parquet — source recipes for offline ingest.
- derived/image_fallback_v2.sqlite — read-only mapping for similar recipe photos.
- derived/extract_ingredients_rule_v1.jsonl — offline extracted ingredient source.

The running app reads recipe records from ES. The mapping is optional: without it,
source photos still work and missing photos use the shipped SVG category icons.
No command in app startup or CI automatically imports data, writes to ES, or
rebuilds a mapping. Use recipe-ingest --help before intentional offline writes.
