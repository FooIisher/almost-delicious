"""Generated BM25 matching vocabulary.

The file is built from the recipe data and is not committed. Generate it before
running extraction, tests against real data or the app:

    uv run python scripts/build_bm25_vocabulary.py
"""

import json
from functools import lru_cache

from recipe_search.settings import get_settings

BUILD_HINT = (
    "Generate it first with `uv run python scripts/build_bm25_vocabulary.py` "
    "(see docs/data-pipeline.md), or point BM25_VOCABULARY to an existing file."
)


class VocabularyMissingError(FileNotFoundError):
    """Raised when the generated vocabulary has not been built yet."""


def vocabulary_path():
    return get_settings().vocabulary_file


@lru_cache(maxsize=1)
def load_vocabulary():
    path = vocabulary_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VocabularyMissingError(f"BM25 vocabulary not found at {path}. {BUILD_HINT}") from exc
