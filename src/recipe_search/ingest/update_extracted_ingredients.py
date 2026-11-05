from recipe_search.settings import get_settings

"""Partially update existing recipes from the ingredient extraction JSONL."""
import argparse
import json
import time
from pathlib import Path

from elasticsearch import helpers

from recipe_search.ingest.ingest_recipes import DEFAULT_ES_URL, DEFAULT_INDEX, connect_elasticsearch
from recipe_search.matching.ingredient_sources import classify_usage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=get_settings().data_file("derived/extract_ingredients_rule_v1.jsonl"),
    )
    parser.add_argument("--es-url", default=DEFAULT_ES_URL)
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without connecting or updating Elasticsearch",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional number of records for validation or a small pilot",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Number of JSONL lines to skip; use the last reported next offset.",
    )
    args = parser.parse_args()
    if args.source is None:
        parser.error("Supply --source or set DATA_DIR")
    if args.batch_size < 1 or args.offset < 0 or args.sleep < 0 or args.limit < 0:
        parser.error("batch-size must be positive; offset, sleep and limit must be nonnegative")

    client = None if args.dry_run else connect_elasticsearch(args.es_url)
    try:
        if client is not None and not client.indices.exists(index=args.index):
            raise RuntimeError(f"Index does not exist: {args.index}")
        settings = (
            client.indices.get_settings(index=args.index)
            if client
            else {args.index: {"settings": {"index": {}}}}
        )
        normalizers = (
            settings[args.index]["settings"]["index"].get("analysis", {}).get("normalizer", {})
        )
        field = {"type": "keyword"}
        if "lowercase_keyword" in normalizers:
            field["normalizer"] = "lowercase_keyword"
        if client:
            client.indices.put_mapping(
                index=args.index,
                properties={
                    "extract_ingredients": field,
                    "extract_ingredients_firm": field,
                    "extract_evidence": {"type": "object", "enabled": False},
                    "extraction_version": {"type": "keyword"},
                },
            )
        updated = 0
        batch = []
        batch_start = args.offset

        def flush(next_offset):
            nonlocal updated, batch_start
            failures = []
            try:
                for ok, item in (
                    []
                    if args.dry_run
                    else helpers.streaming_bulk(
                        client,
                        batch,
                        chunk_size=args.batch_size,
                        max_retries=3,
                        initial_backoff=2,
                        max_backoff=30,
                        raise_on_error=False,
                    )
                ):
                    if not ok:
                        failures.append(item)
            except Exception:
                print(f"Resume safely with --offset {batch_start}", flush=True)
                raise
            if failures:
                print(json.dumps(failures[:5], ensure_ascii=False), flush=True)
                raise RuntimeError(
                    f"{len(failures)} updates failed. Resume with --offset {batch_start}"
                )
            updated += len(batch)
            print(
                f"{'Validated' if args.dry_run else 'Updated'} {updated}; next offset: {next_offset}",
                flush=True,
            )
            batch.clear()
            batch_start = next_offset
            time.sleep(args.sleep)

        with args.source.open(encoding="utf-8") as source:
            next_offset = args.offset
            for offset, line in enumerate(source):
                if offset < args.offset:
                    continue
                record = json.loads(line)
                if args.limit and offset - args.offset >= args.limit:
                    break
                terms = record["extract_ingredients"]
                if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
                    raise ValueError(f"Invalid ingredients on line {offset + 1}")
                evidence = [
                    {
                        **item,
                        "usage": classify_usage(
                            item.get("text", ""), item.get("hedged", False), item.get("ingredient")
                        ),
                    }
                    for item in record.get("extract_evidence", [])
                    if isinstance(item, dict)
                ]
                firm = [
                    term
                    for term in terms
                    if any(
                        item.get("ingredient", "").strip().casefold() == term.strip().casefold()
                        and item["usage"] == "preparation"
                        for item in evidence
                    )
                ]
                batch.append(
                    {
                        "_op_type": "update",
                        "_index": args.index,
                        "_id": str(record["recipeid"]),
                        "doc": {
                            "extract_ingredients": list(
                                dict.fromkeys(
                                    term.strip().lower() for term in terms if term.strip()
                                )
                            ),
                            "extract_ingredients_firm": list(
                                dict.fromkeys(term.strip().lower() for term in firm)
                            ),
                            "extract_evidence": evidence,
                            "extraction_version": str(record.get("extraction_version", "unknown"))
                            + "-usage-v1",
                        },
                    }
                )
                next_offset = offset + 1
                if len(batch) >= args.batch_size:
                    flush(next_offset)
            if batch:
                flush(next_offset)
        if client:
            client.indices.refresh(index=args.index)
        print(
            f"Completed: {updated} recipes "
            + ("validated; no Elasticsearch writes." if args.dry_run else "updated."),
            flush=True,
        )
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    main()
