import argparse
import json
from pathlib import Path

import pandas as pd

from recipe_search.ingest.ingest_recipes import parse_r_vector
from recipe_search.matching.tag_normalization import normalize_tags
from recipe_search.settings import get_settings, missing_data_message


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Build the generated matching vocabulary from Parquet (not versioned); "
            "does not modify Elasticsearch. Run before extraction and the app."
        )
    )
    parser.add_argument("--source", type=Path, default=get_settings().data_file("recipes.parquet"))
    parser.add_argument(
        "--output",
        type=Path,
        default=get_settings().vocabulary_file,
        help="Defaults to the path the app reads (BM25_VOCABULARY or package config/).",
    )
    args = parser.parse_args()
    if args.source is None:
        parser.error("Supply --source or set DATA_DIR")
    if not args.source.is_file():
        parser.error(missing_data_message(args.source))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data = pd.read_parquet(
        args.source, columns=["recipeingredientparts", "keywords", "recipecategory"]
    )
    fields = {
        field: set() for field in ("ingredients", "ingredients_raw", "keywords", "recipecategory")
    }
    for record in data.itertuples(index=False):
        fields["ingredients_raw"].update(parse_r_vector(record.recipeingredientparts))
        fields["ingredients"].update(
            " ".join(value.casefold().split())
            for value in parse_r_vector(record.recipeingredientparts)
        )
        fields["keywords"].update(normalize_tags(parse_r_vector(record.keywords)))
        fields["recipecategory"].update(normalize_tags(record.recipecategory))
    # Preserve the independently refreshed ES vocabulary for instruction-extracted terms.
    previous = json.loads(args.output.read_text()) if args.output.exists() else {}
    fields["extract_ingredients"] = set(previous.get("fields", {}).get("extract_ingredients", []))
    payload = {
        "version": 3,
        "source": args.source.name,
        "recipe_count": len(data),
        "fields": {field: sorted(values) for field, values in fields.items()},
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    print({field: len(values) for field, values in fields.items()})
    print(f"Wrote {args.output}; restart the app to load it.")


if __name__ == "__main__":
    main()
