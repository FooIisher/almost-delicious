"""Settings-aware local service entry point."""

import argparse
import sys

import uvicorn

from recipe_search.settings import get_settings


def main():
    parser = argparse.ArgumentParser(description="Start Almost Delicious locally")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    settings = get_settings()
    if not settings.vocabulary_file.is_file():
        print(
            f"Warning: matching vocabulary missing at {settings.vocabulary_file}. "
            "Run `uv run python scripts/build_bm25_vocabulary.py` first "
            "(see docs/data-pipeline.md).",
            file=sys.stderr,
        )
    uvicorn.run(
        "recipe_search.api.app:app",
        host=args.host or settings.app_host,
        port=args.port if args.port is not None else settings.app_port,
    )


if __name__ == "__main__":
    main()
