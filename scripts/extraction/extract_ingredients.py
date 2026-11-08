"""Extract ingredients mentioned in recipe instructions (rule-v1, no LLM, no ES writes).

Reads DATA_DIR/recipes.parquet and the generated matching vocabulary, and writes one
JSON line per recipe plus a stats file. Load the result into ES afterwards with
``python -m recipe_search.ingest.update_extracted_ingredients``.

Build the vocabulary first: ``uv run python scripts/build_bm25_vocabulary.py``.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rules import VERSION, Extractor  # noqa: E402

from recipe_search.ingest.ingest_recipes import parse_r_vector  # noqa: E402
from recipe_search.matching.vocabulary import VocabularyMissingError, load_vocabulary  # noqa: E402
from recipe_search.settings import get_settings, missing_data_message  # noqa: E402

COLUMNS = ["recipeid", "recipeingredientparts", "recipeingredientquantities", "recipeinstructions"]
DEFAULT_NAME = f"extract_ingredients_{VERSION.replace('-', '_')}"


def parse_args():
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=settings.data_file("recipes.parquet"))
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.derived_dir / f"{DEFAULT_NAME}.jsonl",
        help="Defaults to var/derived/extract_ingredients_rule_v1.jsonl (WORK_DIR).",
    )
    parser.add_argument("--start", type=int, default=0, help="First source row (inclusive).")
    parser.add_argument("--end", type=int, default=None, help="Last source row (exclusive).")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output.")
    args = parser.parse_args()
    if args.source is None or args.output is None:
        parser.error("Set DATA_DIR or supply both --source and --output")
    if not args.source.is_file():
        parser.error(missing_data_message(args.source))
    if args.start < 0 or (args.end is not None and args.end <= args.start):
        parser.error("Require 0 <= --start < --end")
    if args.output.exists() and not args.force:
        parser.error(f"{args.output} exists; pass --force to overwrite it")
    return args


def iter_rows(source, start, end, batch_size):
    offset = 0
    for batch in pq.ParquetFile(source).iter_batches(batch_size=batch_size, columns=COLUMNS):
        rows = batch.num_rows
        lo, hi = max(start - offset, 0), rows if end is None else min(end - offset, rows)
        offset += rows
        if hi <= 0:
            if end is not None and offset >= end:
                break
            continue
        columns = [batch.column(name).to_pylist()[lo:hi] for name in COLUMNS]
        yield from zip(*columns)
        if end is not None and offset >= end:
            break


def main():
    args = parse_args()
    try:
        vocabulary = load_vocabulary()
    except VocabularyMissingError as exc:
        raise SystemExit(str(exc)) from None
    extractor = Extractor(vocabulary["fields"]["ingredients"])
    stats = Counter()
    firm_terms = Counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    with partial.open("w", encoding="utf-8") as out:
        for recipeid, parts, quantities, instructions in iter_rows(
            args.source, args.start, args.end, args.batch_size
        ):
            record = extractor.extract(
                recipeid,
                parse_r_vector(parts) or [],
                parse_r_vector(quantities) or [],
                parse_r_vector(instructions) or [],
            )
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            firm = [item["ingredient"] for item in record["extract_evidence"] if not item["hedged"]]
            stats["recipes"] += 1
            stats["recipes_with_terms"] += bool(record["extract_ingredients"])
            stats["recipes_with_non_hedged_terms"] += bool(firm)
            stats["terms"] += len(record["extract_ingredients"])
            stats["non_hedged_terms"] += len(firm)
            stats["ingredient_list_incomplete"] += record["ingredient_list_incomplete"]
            firm_terms.update(firm)
            if stats["recipes"] % 50000 == 0:
                print(f"Processed {stats['recipes']} recipes", flush=True)
    partial.replace(args.output)
    summary = dict(
        version=VERSION,
        source=args.source.name,
        rows=dict(start=args.start, end=args.end),
        vocabulary=str(get_settings().vocabulary_file),
        **stats,
        top_non_hedged_terms=firm_terms.most_common(30),
    )
    stats_path = args.output.with_name(args.output.stem + "_stats.json")
    stats_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "top_non_hedged_terms"}))
    print(f"Wrote {args.output} and {stats_path}; Elasticsearch unchanged.")


if __name__ == "__main__":
    main()
