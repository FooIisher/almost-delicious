from recipe_search.settings import get_settings

"""Read ES keyword terms into local matching vocabulary; never changes the index."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    from recipe_search.api.search import get_client
    from recipe_search.retrieval.semantic_search import DEFAULT_INDEX

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=get_settings().output_dir / "bm25_vocabulary.json"
    )
    args = parser.parse_args()
    client = get_client()
    after = None
    terms = set()
    while True:
        composite = {
            "size": 1000,
            "sources": [{"ingredient": {"terms": {"field": "extract_ingredients"}}}],
        }
        if after:
            composite["after"] = after
        response = client.search(
            index=DEFAULT_INDEX, size=0, aggregations={"vocabulary": {"composite": composite}}
        )
        result = response["aggregations"]["vocabulary"]
        terms.update(bucket["key"]["ingredient"] for bucket in result["buckets"])
        after = result.get("after_key")
        if not after or not result["buckets"]:
            break
    payload = json.loads(args.output.read_text())
    payload["fields"]["extract_ingredients"] = sorted(terms)
    payload["version"] = 3
    payload["extract_ingredients_source"] = dict(index=DEFAULT_INDEX, field="extract_ingredients")
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(
        f"Updated local extract_ingredients vocabulary: {len(terms)} terms; Elasticsearch unchanged."
    )


if __name__ == "__main__":
    main()
