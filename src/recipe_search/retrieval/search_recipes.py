#!/usr/bin/env python3
"""Convert user text to a BGE vector and search matching recipes."""

from __future__ import annotations

import argparse
import json
from typing import Any

from recipe_search.retrieval.semantic_search import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ES_URL,
    DEFAULT_INDEX,
    QUERY_PREFIX,
    connect_elasticsearch,
    load_embedding_model,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Encode user text with BGE and run Elasticsearch kNN search."
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Natural-language query. If omitted, the script prompts for input.",
    )
    parser.add_argument("--es-url", default=DEFAULT_ES_URL, help="Elasticsearch base URL.")
    parser.add_argument("--index", default=DEFAULT_INDEX, help="Elasticsearch index name.")
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Sentence Transformers model used to encode the query.",
    )
    parser.add_argument("--k", type=int, default=5, help="Number of results to return.")
    parser.add_argument(
        "--num-candidates",
        type=int,
        default=20,
        help="Approximate kNN candidate pool size.",
    )
    return parser.parse_args()


def resolve_query(query_parts: list[str]) -> str:
    query = " ".join(query_parts).strip()
    if not query:
        query = input("Enter recipe search text: ").strip()
    if not query:
        raise SystemExit("Search text cannot be empty.")
    return query


def encode_query(model: Any, query: str) -> list[float]:
    embedding = model.encode(
        QUERY_PREFIX + query,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return embedding.astype(float).tolist()


def encode_weighted(model, main, scope="", alpha=1.0, beta=0.30):
    if (
        not scope.strip()
        or beta == 0
        or " ".join(main.casefold().split()) == " ".join(scope.casefold().split())
    ):
        return encode_query(model, main)
    import numpy as np

    values = model.encode(
        [QUERY_PREFIX + main, QUERY_PREFIX + scope],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    vector = alpha * values[0] + beta * values[1]
    length = np.linalg.norm(vector)
    if not np.isfinite(length) or length <= 0:
        raise ValueError("Invalid weighted query vector")
    return (vector / length).astype(float).tolist()


def search_recipes(
    client: Any,
    index_name: str,
    query_vector: list[float],
    k: int,
    num_candidates: int,
) -> list[dict[str, Any]]:
    if k <= 0:
        raise ValueError("--k must be greater than 0")
    if num_candidates < k:
        raise ValueError("--num-candidates must be greater than or equal to --k")

    response = client.search(
        index=index_name,
        size=k,
        source=[
            "recipeid",
            "name",
            "description",
            "recipecategory",
            "keywords",
            "ingredients",
            "extract_ingredients",
            "total_time_minutes",
            "aggregatedrating",
            "image_urls",
        ],
        knn={
            "field": "content_vector",
            "query_vector": query_vector,
            "k": k,
            "num_candidates": num_candidates,
        },
    )

    results = []
    for rank, hit in enumerate(response["hits"]["hits"], start=1):
        results.append(
            {
                "rank": rank,
                "score": hit["_score"],
                **hit["_source"],
            }
        )
    return results


def main() -> None:
    args = parse_args()
    query = resolve_query(args.query)

    client = connect_elasticsearch(args.es_url)
    model = load_embedding_model(args.embedding_model)
    query_vector = encode_query(model, query)
    results = search_recipes(
        client=client,
        index_name=args.index,
        query_vector=query_vector,
        k=args.k,
        num_candidates=args.num_candidates,
    )

    output = {
        "query": query,
        "embedding_model": args.embedding_model,
        "vector_dimensions": len(query_vector),
        "query_vector": query_vector,
        "result_count": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
