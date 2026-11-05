#!/usr/bin/env python3
"""Run a small BGE vector search against recipes_clean."""

from __future__ import annotations

import argparse
from typing import Any
from urllib.parse import urlparse, urlunparse

try:
    from elasticsearch import Elasticsearch
except ImportError as exc:  # pragma: no cover - user-facing startup guard
    raise SystemExit(
        "Missing dependency: elasticsearch\nInstall it with: python -m pip install elasticsearch"
    ) from exc


# Keep credentials configurable for deployments while retaining the local prototype
# defaults used by the recipe cluster.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

from recipe_search.settings import get_settings

DEFAULT_ES_URL = get_settings().es_url
DEFAULT_INDEX = get_settings().es_index
DEFAULT_EMBEDDING_MODEL = get_settings().embedding_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search recipes_clean using BGE vector search.")
    parser.add_argument("query", help="Natural language recipe search query.")
    parser.add_argument("--es-url", default=DEFAULT_ES_URL, help="Elasticsearch base URL.")
    parser.add_argument("--index", default=DEFAULT_INDEX, help="Elasticsearch index name.")
    parser.add_argument(
        "--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help="Sentence Transformers model."
    )
    parser.add_argument("--k", type=int, default=5, help="Number of nearest neighbors to return.")
    parser.add_argument("--num-candidates", type=int, default=20, help="kNN candidate pool size.")
    return parser.parse_args()


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
            request_timeout=60,
        )
        try:
            client.info()
            return client
        except Exception as exc:  # pragma: no cover - depends on local ES state
            last_error = exc

    raise RuntimeError(
        f"Could not connect to Elasticsearch at {', '.join(urls_to_try)}"
    ) from last_error


def load_embedding_model(model_name: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - user-facing startup guard
        raise RuntimeError(
            "Missing dependency: sentence-transformers\n"
            "Install it with: python -m pip install sentence-transformers"
        ) from exc

    model = SentenceTransformer(model_name)
    model.max_seq_length = 512
    return model


def main() -> None:
    args = parse_args()
    client = connect_elasticsearch(args.es_url)
    model = load_embedding_model(args.embedding_model)

    query_vector = (
        model.encode(
            QUERY_PREFIX + args.query,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        .astype(float)
        .tolist()
    )

    response = client.search(
        index=args.index,
        size=args.k,
        source=[
            "recipeid",
            "name",
            "recipecategory",
            "ingredients",
            "total_time_minutes",
        ],
        knn={
            "field": "content_vector",
            "query_vector": query_vector,
            "k": args.k,
            "num_candidates": args.num_candidates,
        },
    )

    for hit in response["hits"]["hits"]:
        source = hit["_source"]
        print(f"{hit['_score']:.4f}  {source.get('recipeid')}  {source.get('name')}")
        print(f"        category: {source.get('recipecategory')}")
        print(f"        ingredients: {', '.join(source.get('ingredients') or [])}")
        print(f"        total_time_minutes: {source.get('total_time_minutes')}")


if __name__ == "__main__":
    main()
