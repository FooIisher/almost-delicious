#!/usr/bin/env python3
"""Import a small Food.com recipe sample into local Elasticsearch."""

from __future__ import annotations

import argparse
import csv
import math
import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse, urlunparse

import pandas as pd
import pyarrow.parquet as pq

from recipe_search.matching.tag_normalization import normalize_tags
from recipe_search.settings import get_settings

try:
    from elasticsearch import Elasticsearch, helpers
except ImportError as exc:  # pragma: no cover - user-facing startup guard
    raise SystemExit(
        "Missing dependency: elasticsearch\nInstall it with: python -m pip install elasticsearch"
    ) from exc


DEFAULT_LIMIT: int | None = None
DEFAULT_BULK_CHUNK_SIZE = 1000
DEFAULT_BULK_MAX_RETRIES = 3
DEFAULT_BULK_SLEEP_EVERY = 1000
DEFAULT_BULK_SLEEP_SECONDS = 1.0
EMBEDDING_DIMS = 768
# Keep the large source dataset outside the self-contained prototype folder.
DEFAULT_RECIPES_PARQUET = get_settings().data_file("recipes.parquet")
RECIPES_PARQUET_URL = (
    "https://588738577887-baselight-crawlers-prod-ue1-datasets.s3.us-east-1.amazonaws.com/"
    "kaggle-datasets/irkaal/foodcom-recipes-and-reviews/"
    "recipes_v2025-01-04_75da657c.parquet"
)

RECIPE_COLUMNS = [
    "recipeid",
    "name",
    "cooktime",
    "preptime",
    "totaltime",
    "description",
    "images",
    "recipecategory",
    "keywords",
    "recipeingredientquantities",
    "recipeingredientparts",
    "aggregatedrating",
    "reviewcount",
    "calories",
    "fatcontent",
    "saturatedfatcontent",
    "cholesterolcontent",
    "sodiumcontent",
    "carbohydratecontent",
    "fibercontent",
    "sugarcontent",
    "proteincontent",
    "recipeservings",
    "recipeyield",
    "recipeinstructions",
]

DEFAULT_ES_URL = get_settings().es_url
DEFAULT_INDEX = get_settings().es_index
DEFAULT_EMBEDDING_MODEL = get_settings().embedding_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Food.com recipe rows from Baselight Parquet into Elasticsearch."
    )
    parser.add_argument("--es-url", default=DEFAULT_ES_URL, help="Elasticsearch base URL.")
    parser.add_argument("--index", default=DEFAULT_INDEX, help="Destination index name.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Number of rows to import. Defaults to all rows.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Number of rows to skip before importing.",
    )
    parser.add_argument(
        "--recipe-ids",
        nargs="+",
        default=None,
        help="Only import these recipe ids. Values may be separated by spaces or commas.",
    )
    parser.add_argument(
        "--recipe-ids-file",
        default=None,
        help="Path to a text file containing recipe ids, one id or comma-separated ids per line.",
    )
    parser.add_argument(
        "--with-embeddings",
        action="store_true",
        help="Generate BGE embeddings and store them in content_vector.",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Sentence Transformers model used when --with-embeddings is set.",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=16,
        help="Batch size for embedding generation.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help=(
            "DELETE the destination index and create it again before importing. "
            "Without this flag an existing index is always kept."
        ),
    )
    parser.add_argument(
        "--keep-index",
        action="store_true",
        help="Deprecated no-op: the index is kept unless --recreate is given.",
    )
    parser.add_argument(
        "--bulk-chunk-size",
        type=int,
        default=DEFAULT_BULK_CHUNK_SIZE,
        help="Number of recipes to index per bulk request.",
    )
    parser.add_argument(
        "--bulk-max-retries",
        type=int,
        default=DEFAULT_BULK_MAX_RETRIES,
        help="Number of retries for a failed bulk batch.",
    )
    parser.add_argument(
        "--bulk-sleep",
        type=float,
        default=DEFAULT_BULK_SLEEP_SECONDS,
        help="Seconds to sleep after every --bulk-sleep-every successfully indexed recipes.",
    )
    parser.add_argument(
        "--bulk-sleep-every",
        type=int,
        default=DEFAULT_BULK_SLEEP_EVERY,
        help="Sleep after this many successfully indexed recipes.",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Skip the final index refresh after importing.",
    )
    parser.add_argument(
        "--source-url",
        default=str(DEFAULT_RECIPES_PARQUET) if DEFAULT_RECIPES_PARQUET else None,
        help="Recipes Parquet URL or absolute local path; defaults to DATA_DIR/recipes.parquet.",
    )
    args = parser.parse_args()
    if args.recreate and args.keep_index:
        parser.error("--recreate and --keep-index cannot be combined")
    if args.recreate and (args.offset > 0 or args.recipe_ids or args.recipe_ids_file):
        parser.error("--recreate rebuilds the whole index; do not combine it with --offset or ids")
    if not args.source_url:
        parser.error("Supply --source-url or set DATA_DIR to an absolute directory")
    return args


def parse_recipe_ids(values: list[str] | None, file_path: str | None) -> list[str]:
    recipe_ids: list[str] = []

    for value in values or []:
        recipe_ids.extend(part.strip() for part in value.split(",") if part.strip())

    if file_path:
        with open(file_path, encoding="utf-8") as id_file:
            for line in id_file:
                line = line.split("#", 1)[0]
                recipe_ids.extend(part.strip() for part in line.split(",") if part.strip())

    seen_ids: set[str] = set()
    unique_ids: list[str] = []
    for recipe_id in recipe_ids:
        if recipe_id not in seen_ids:
            seen_ids.add(recipe_id)
            unique_ids.append(recipe_id)
    return unique_ids


def clean_value(value: Any) -> Any:
    if value is pd.NA or value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "na", "nan", "null", "none"}:
        return None
    return value


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: clean_value(value) for key, value in record.items()}


def parse_r_vector(value: Any, *, preserve_empty: bool = False) -> list[str]:
    value = clean_value(value)
    if value is None:
        return []
    if not isinstance(value, str):
        return [str(value)]

    text = value.strip()
    if text.lower() in {"character(0)", "numeric(0)", "integer(0)", "logical(0)", "c()"}:
        return []
    if text.startswith("c(") and text.endswith(")"):
        text = text[2:-1]
    text = re.sub(r"\s*\n\s*", " ", text)

    rows = csv.reader([text], skipinitialspace=True, quotechar='"', escapechar="\\")
    parsed = next(rows, [])
    values = []
    for item in parsed:
        item = item.strip()
        if clean_value(item) is None:
            if preserve_empty:
                values.append("")
            continue
        values.append(item)
    return values


def parse_duration_minutes(value: Any) -> int | None:
    value = clean_value(value)
    if value is None:
        return None

    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        str(value).strip(),
    )
    if not match:
        return None

    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    total_minutes = days * 24 * 60 + hours * 60 + minutes
    if seconds:
        total_minutes += math.ceil(seconds / 60)
    return total_minutes


def parse_time_limit_tag_minutes(record: dict[str, Any]) -> int | None:
    tag_values = []
    if record.get("recipecategory"):
        category = record["recipecategory"]
        tag_values.extend(category if isinstance(category, list) else [str(category)])
    tag_values.extend(str(keyword) for keyword in record.get("keywords") or [])

    limits = []
    for tag_value in tag_values:
        match = re.search(r"<\s*(\d+)\s*mins?", tag_value, flags=re.IGNORECASE)
        if match:
            limits.append(int(match.group(1)))
    return min(limits) if limits else None


def backfill_time_fields(recipe: dict[str, Any]) -> None:
    cook_time = recipe.get("cook_time_minutes")
    prep_time = recipe.get("prep_time_minutes")
    total_time = recipe.get("total_time_minutes")
    time_limit = parse_time_limit_tag_minutes(recipe)

    if cook_time is None and prep_time is not None and total_time is not None:
        recipe["cook_time_minutes"] = max(total_time - prep_time, 0)
        cook_time = recipe["cook_time_minutes"]

    if total_time is None and time_limit is not None:
        recipe["total_time_minutes"] = time_limit
        total_time = time_limit

    if prep_time is None and cook_time is not None and total_time is not None:
        recipe["prep_time_minutes"] = max(total_time - cook_time, 0)
        prep_time = recipe["prep_time_minutes"]

    if time_limit is not None:
        if recipe.get("cook_time_minutes") is None:
            recipe["cook_time_minutes"] = time_limit
        if recipe.get("prep_time_minutes") is None:
            recipe["prep_time_minutes"] = time_limit


def to_int(value: Any) -> int | None:
    value = clean_value(value)
    if value is None:
        return None
    return int(value)


def build_searchable_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ["name", "description", "recipecategory"]:
        value = record.get(field)
        if value:
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            else:
                parts.append(str(value))

    parts.extend(record.get("keywords") or [])
    parts.extend(record.get("ingredients") or [])
    if record.get("instructions_text"):
        parts.append(record["instructions_text"])
    return "\n".join(parts)


def build_embedding_text(record: dict[str, Any]) -> str:
    sections = [
        ("title", record.get("name")),
        (
            "category",
            ", ".join(record["recipecategory"])
            if isinstance(record.get("recipecategory"), list)
            else record.get("recipecategory"),
        ),
        ("description", record.get("description")),
        ("keywords", ", ".join(record.get("keywords") or [])),
        ("ingredients", ", ".join(record.get("ingredients") or [])),
        ("instructions", record.get("instructions_text")),
    ]
    return "\n".join(f"{label}: {value}" for label, value in sections if value)


def transform_recipe_record(raw_record: dict[str, Any]) -> dict[str, Any]:
    record = clean_record(raw_record)
    instructions = parse_r_vector(record.get("recipeinstructions"))

    clean_recipe = {
        "recipeid": str(record["recipeid"]),
        "name": record.get("name"),
        "description": record.get("description"),
        "image_urls": parse_r_vector(record.get("images")),
        "recipecategory": record.get("recipecategory"),
        "keywords": parse_r_vector(record.get("keywords")),
        "ingredient_quantities": parse_r_vector(
            record.get("recipeingredientquantities"),
            preserve_empty=True,
        ),
        "ingredients": parse_r_vector(record.get("recipeingredientparts")),
        "aggregatedrating": record.get("aggregatedrating"),
        "reviewcount": to_int(record.get("reviewcount")),
        "calories": record.get("calories"),
        "fatcontent": record.get("fatcontent"),
        "saturatedfatcontent": record.get("saturatedfatcontent"),
        "cholesterolcontent": record.get("cholesterolcontent"),
        "sodiumcontent": record.get("sodiumcontent"),
        "carbohydratecontent": record.get("carbohydratecontent"),
        "fibercontent": record.get("fibercontent"),
        "sugarcontent": record.get("sugarcontent"),
        "proteincontent": record.get("proteincontent"),
        "recipeservings": record.get("recipeservings"),
        "recipeyield": record.get("recipeyield"),
        "cook_time_minutes": parse_duration_minutes(record.get("cooktime")),
        "prep_time_minutes": parse_duration_minutes(record.get("preptime")),
        "total_time_minutes": parse_duration_minutes(record.get("totaltime")),
        "instructions": instructions,
        "instructions_text": "\n".join(instructions),
    }
    backfill_time_fields(clean_recipe)
    clean_recipe["searchable_text"] = build_searchable_text(clean_recipe)
    clean_recipe["embedding_text"] = build_embedding_text(clean_recipe)
    # Keep derived texts on the original source representation, matching existing
    # embeddings. Only the two structured tag fields use the normalized arrays.
    clean_recipe["keywords"] = normalize_tags(clean_recipe["keywords"])
    clean_recipe["recipecategory"] = normalize_tags(clean_recipe.get("recipecategory"))
    return {key: value for key, value in clean_recipe.items() if value is not None}


def localhost_fallback_url(es_url: str) -> str | None:
    parsed_url = urlparse(es_url)
    if parsed_url.hostname != "localhost":
        return None

    fallback_netloc = parsed_url.netloc.replace("localhost", "127.0.0.1", 1)
    return urlunparse(parsed_url._replace(netloc=fallback_netloc))


def connect_elasticsearch(es_url: str) -> Elasticsearch:
    urls_to_try = [es_url]
    fallback_url = localhost_fallback_url(es_url)
    if fallback_url:
        urls_to_try.append(fallback_url)

    last_error: Exception | None = None
    for url in urls_to_try:
        client = Elasticsearch(
            url,
            **get_settings().es_options(url),
            request_timeout=120,
            retry_on_timeout=True,
            max_retries=5,
        )
        try:
            info = client.info()
            print(f"Connected to Elasticsearch {info['version']['number']} at {url}")
            return client
        except Exception as exc:  # pragma: no cover - depends on local ES state
            last_error = exc

    raise RuntimeError(
        f"Could not connect to Elasticsearch at {', '.join(urls_to_try)}"
    ) from last_error


def ensure_index(client: Elasticsearch, index_name: str, recreate: bool) -> None:
    if recreate and client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)

    if client.indices.exists(index=index_name):
        client.indices.put_mapping(
            index=index_name,
            properties={
                "embedding_text": {"type": "text"},
                "content_vector": {
                    "type": "dense_vector",
                    "dims": EMBEDDING_DIMS,
                    "index": True,
                    "similarity": "cosine",
                },
            },
        )
        return

    client.indices.create(
        index=index_name,
        settings={
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "normalizer": {
                    "lowercase_keyword": {
                        "type": "custom",
                        "filter": ["lowercase"],
                    }
                }
            },
        },
        mappings={
            "properties": {
                "recipeid": {"type": "keyword"},
                "name": {
                    "type": "text",
                    "fields": {
                        "keyword": {
                            "type": "keyword",
                            "normalizer": "lowercase_keyword",
                        }
                    },
                },
                "description": {"type": "text"},
                "image_urls": {"type": "keyword"},
                "recipecategory": {"type": "keyword", "normalizer": "lowercase_keyword"},
                "keywords": {"type": "keyword", "normalizer": "lowercase_keyword"},
                "ingredient_quantities": {"type": "keyword"},
                "ingredients": {"type": "keyword", "normalizer": "lowercase_keyword"},
                "aggregatedrating": {"type": "float"},
                "reviewcount": {"type": "integer"},
                "calories": {"type": "float"},
                "fatcontent": {"type": "float"},
                "saturatedfatcontent": {"type": "float"},
                "cholesterolcontent": {"type": "float"},
                "sodiumcontent": {"type": "float"},
                "carbohydratecontent": {"type": "float"},
                "fibercontent": {"type": "float"},
                "sugarcontent": {"type": "float"},
                "proteincontent": {"type": "float"},
                "recipeservings": {"type": "float"},
                "recipeyield": {"type": "keyword"},
                "cook_time_minutes": {"type": "integer"},
                "prep_time_minutes": {"type": "integer"},
                "total_time_minutes": {"type": "integer"},
                "instructions": {"type": "text"},
                "instructions_text": {"type": "text"},
                "searchable_text": {"type": "text"},
                "embedding_text": {"type": "text"},
                "content_vector": {
                    "type": "dense_vector",
                    "dims": EMBEDDING_DIMS,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    )


def iter_recipe_batches(
    source_url: str,
    limit: int | None,
    offset: int,
    batch_size: int,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be greater than 0")
    if offset < 0:
        raise ValueError("--offset must be greater than or equal to 0")
    if batch_size <= 0:
        raise ValueError("--bulk-chunk-size must be greater than 0")

    parsed_source = urlparse(source_url)
    if parsed_source.scheme and parsed_source.scheme != "file":
        data_frame = pd.read_parquet(source_url, columns=RECIPE_COLUMNS)
        if offset > 0:
            data_frame = data_frame.iloc[offset:]
        if limit is not None:
            data_frame = data_frame.head(limit)

        total_rows = len(data_frame)
        for start_index in range(0, total_rows, batch_size):
            end_index = min(start_index + batch_size, total_rows)
            batch_frame = data_frame.iloc[start_index:end_index]
            records = batch_frame.to_dict(orient="records")
            source_offset = offset + start_index
            yield source_offset, [transform_recipe_record(record) for record in records]
        return

    parquet_path = parsed_source.path if parsed_source.scheme == "file" else source_url
    parquet_file = pq.ParquetFile(parquet_path)
    source_offset = 0
    yielded_count = 0

    for record_batch in parquet_file.iter_batches(batch_size=batch_size, columns=RECIPE_COLUMNS):
        batch_row_count = record_batch.num_rows
        batch_start_offset = source_offset
        batch_end_offset = batch_start_offset + batch_row_count
        source_offset = batch_end_offset

        if batch_end_offset <= offset:
            continue

        relative_start = max(offset - batch_start_offset, 0)
        available_count = batch_row_count - relative_start
        if limit is not None:
            remaining_count = limit - yielded_count
            if remaining_count <= 0:
                break
            available_count = min(available_count, remaining_count)

        sliced_batch = record_batch.slice(relative_start, available_count)
        batch_frame = sliced_batch.to_pandas()
        records = batch_frame.to_dict(orient="records")
        yielded_count += available_count
        yield (
            batch_start_offset + relative_start,
            [transform_recipe_record(record) for record in records],
        )


def iter_recipe_batches_by_ids(
    source_url: str,
    recipe_ids: list[str],
    batch_size: int,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    if batch_size <= 0:
        raise ValueError("--bulk-chunk-size must be greater than 0")

    target_ids = set(recipe_ids)
    parsed_source = urlparse(source_url)

    if parsed_source.scheme and parsed_source.scheme != "file":
        data_frame = pd.read_parquet(source_url, columns=RECIPE_COLUMNS)
        id_series = data_frame["recipeid"].astype(str)
        matched_frame = data_frame[id_series.isin(target_ids)]
        for start_index in range(0, len(matched_frame), batch_size):
            batch_frame = matched_frame.iloc[start_index : start_index + batch_size]
            records = batch_frame.to_dict(orient="records")
            yield start_index, [transform_recipe_record(record) for record in records]
        return

    parquet_path = parsed_source.path if parsed_source.scheme == "file" else source_url
    parquet_file = pq.ParquetFile(parquet_path)
    source_offset = 0

    for record_batch in parquet_file.iter_batches(batch_size=batch_size, columns=RECIPE_COLUMNS):
        batch_start_offset = source_offset
        source_offset += record_batch.num_rows

        batch_frame = record_batch.to_pandas()
        id_series = batch_frame["recipeid"].astype(str)
        matched_frame = batch_frame[id_series.isin(target_ids)]
        if matched_frame.empty:
            continue

        records = matched_frame.to_dict(orient="records")
        yield batch_start_offset, [transform_recipe_record(record) for record in records]


def load_embedding_model(model_name: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - user-facing startup guard
        raise SystemExit(
            "Missing dependency: sentence-transformers\n"
            "Install it with: python -m pip install sentence-transformers"
        ) from exc

    model = SentenceTransformer(model_name)
    model.max_seq_length = 512
    return model


def add_content_vectors(records: list[dict[str, Any]], model: Any, batch_size: int) -> None:
    texts = [record["embedding_text"] for record in records]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    for record, embedding in zip(records, embeddings, strict=True):
        record["content_vector"] = embedding.astype(float).tolist()


def bulk_index_recipes(
    client: Elasticsearch,
    index_name: str,
    records: list[dict[str, Any]],
    chunk_size: int,
    max_retries: int,
    sleep_seconds: float,
    sleep_every: int,
    offset: int,
) -> tuple[int, int]:
    if chunk_size <= 0:
        raise ValueError("--bulk-chunk-size must be greater than 0")
    if max_retries < 0:
        raise ValueError("--bulk-max-retries must be greater than or equal to 0")
    if sleep_seconds < 0:
        raise ValueError("--bulk-sleep must be greater than or equal to 0")
    if sleep_every < 0:
        raise ValueError("--bulk-sleep-every must be greater than or equal to 0")

    success_count = 0
    error_count = 0
    total_records = len(records)
    next_sleep_at = sleep_every if sleep_every > 0 else 0

    for start_index in range(0, total_records, chunk_size):
        end_index = min(start_index + chunk_size, total_records)
        source_start_index = offset + start_index + 1
        source_end_index = offset + end_index
        batch_records = records[start_index:end_index]
        actions = [
            {
                "_op_type": "index",
                "_index": index_name,
                "_id": str(record["recipeid"]),
                "_source": record,
            }
            for record in batch_records
        ]

        for attempt in range(max_retries + 1):
            try:
                batch_success_count, batch_error_count = helpers.bulk(
                    client,
                    actions,
                    stats_only=True,
                    chunk_size=len(actions),
                    max_retries=2,
                    initial_backoff=2,
                    max_backoff=30,
                    request_timeout=120,
                    retry_on_status=(429, 502, 503, 504),
                )
                success_count += batch_success_count
                error_count += batch_error_count
                print(
                    f"  indexed source rows {source_start_index}-{source_end_index}: "
                    f"{batch_success_count} indexed, {batch_error_count} errors"
                )
                if (
                    sleep_seconds > 0
                    and sleep_every > 0
                    and success_count >= next_sleep_at
                    and end_index < total_records
                ):
                    print(f"  sleeping {sleep_seconds}s after indexing {success_count} recipes")
                    time.sleep(sleep_seconds)
                    while next_sleep_at <= success_count:
                        next_sleep_at += sleep_every
                break
            except Exception as exc:
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"Bulk batch for source rows {source_start_index}-{source_end_index} failed after "
                        f"{max_retries + 1} attempt(s)"
                    ) from exc

                delay_seconds = min(2**attempt * 2, 30)
                print(
                    f"  source rows {source_start_index}-{source_end_index} failed "
                    f"({exc.__class__.__name__}); retrying in {delay_seconds}s..."
                )
                time.sleep(delay_seconds)

    return success_count, error_count


def main() -> None:
    args = parse_args()
    recipe_ids = parse_recipe_ids(args.recipe_ids, args.recipe_ids_file)

    print(f"Connecting to Elasticsearch: {args.es_url}")
    client = connect_elasticsearch(args.es_url)

    requested_count = (
        f"{len(recipe_ids)} recipe id(s)"
        if recipe_ids
        else (str(args.limit) if args.limit is not None else "all")
    )

    embedding_model = None
    if args.with_embeddings:
        print(f"Loading embedding model: {args.embedding_model}")
        embedding_model = load_embedding_model(args.embedding_model)

    if args.recreate:
        print(f"--recreate: deleting and recreating index {args.index}")
    else:
        print(f"Keeping existing index {args.index} (create it only if missing)")
    ensure_index(client, args.index, recreate=args.recreate)

    if recipe_ids:
        print(f"Reading {requested_count} from Parquet source and updating {args.index}...")
    else:
        print(
            f"Reading {requested_count} recipes from Parquet source after offset {args.offset} "
            f"and indexing into {args.index}..."
        )
    success_count = 0
    error_count = 0
    sample_records: list[dict[str, Any]] = []
    next_sleep_at = args.bulk_sleep_every if args.bulk_sleep_every > 0 else 0
    found_recipe_ids: set[str] = set()

    recipe_batches = (
        iter_recipe_batches_by_ids(args.source_url, recipe_ids, args.bulk_chunk_size)
        if recipe_ids
        else iter_recipe_batches(args.source_url, args.limit, args.offset, args.bulk_chunk_size)
    )

    for batch_offset, records in recipe_batches:
        if embedding_model is not None:
            print(
                f"Embedding source rows {batch_offset + 1}-{batch_offset + len(records)} "
                f"with batch size {args.embedding_batch_size}..."
            )
            add_content_vectors(records, embedding_model, args.embedding_batch_size)

        found_recipe_ids.update(str(record["recipeid"]) for record in records)

        if len(sample_records) < 5:
            sample_records.extend(records[: 5 - len(sample_records)])

        batch_success_count, batch_error_count = bulk_index_recipes(
            client,
            args.index,
            records,
            args.bulk_chunk_size,
            args.bulk_max_retries,
            0,
            0,
            batch_offset,
        )
        success_count += batch_success_count
        error_count += batch_error_count

        if args.bulk_sleep > 0 and args.bulk_sleep_every > 0 and success_count >= next_sleep_at:
            print(f"  sleeping {args.bulk_sleep}s after indexing {success_count} recipes")
            time.sleep(args.bulk_sleep)
            while next_sleep_at <= success_count:
                next_sleep_at += args.bulk_sleep_every

    missing_recipe_ids = [
        recipe_id for recipe_id in recipe_ids if recipe_id not in found_recipe_ids
    ]
    if missing_recipe_ids:
        print("")
        print("Warning: these recipe ids were not found in the source data:")
        for recipe_id in missing_recipe_ids:
            print(f"  - {recipe_id}")

    if args.skip_refresh:
        print(f"Skipping final refresh for {args.index}")
    else:
        client.indices.refresh(index=args.index, request_timeout=120)

    print("")
    print("Import complete")
    print(f"  index: {args.index}")
    print(f"  requested: {requested_count}")
    print(f"  offset: {args.offset}")
    print(f"  indexed: {success_count}")
    print(f"  errors: {error_count}")
    print(f"  embeddings: {'yes' if args.with_embeddings else 'no'}")
    print("  sample recipes:")
    for record in sample_records:
        print(f"    - {record.get('recipeid')}: {record.get('name')}")


if __name__ == "__main__":
    main()
