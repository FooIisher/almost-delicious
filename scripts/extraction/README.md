# Instruction ingredient extraction (rule-v1)

Finds ingredients that recipe instructions mention but `recipeingredientparts`
does not list (for example "cooking spray" or "orange juice"). Rule-based, no
LLM calls and no Elasticsearch writes.

- `rules.py`: normalization, vocabulary filters and the matching rules.
- `supplement.py`: curated ingredient names that rarely appear in ingredient lists.
- `extract_ingredients.py`: command-line runner.

The term list comes from the generated matching vocabulary, so **build the
vocabulary first**:

```bash
uv run python scripts/build_bm25_vocabulary.py
uv run python scripts/extraction/extract_ingredients.py            # all 522,517 recipes
uv run python scripts/extraction/extract_ingredients.py \
  --start 0 --end 1000 --output /abs/path/extract_trial.jsonl      # quick trial
```

Output defaults to `var/derived/extract_ingredients_rule_v1.jsonl`, plus a
`*_stats.json` summary next to it. An existing output is only replaced with
`--force`. The full pipeline order is in [docs/data-pipeline.md](../../docs/data-pipeline.md).
