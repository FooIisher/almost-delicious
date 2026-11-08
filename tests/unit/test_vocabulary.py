"""The real matching vocabulary is generated and git-ignored.

Unit tests always use the small committed fixture so they run on a fresh clone.
The environment variable is set at import, before discovery runs any test.
"""

import os
import tempfile
import unittest
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bm25_vocabulary.json"
os.environ.setdefault("BM25_VOCABULARY", str(FIXTURE))

from recipe_search.matching import vocabulary  # noqa: E402
from recipe_search.settings import Settings  # noqa: E402


class VocabularyTests(unittest.TestCase):
    def test_default_path_is_work_dir(self):
        settings = Settings(_env_file=None, bm25_vocabulary="", work_dir="/work/root")
        self.assertEqual(settings.vocabulary_file, Path("/work/root/bm25_vocabulary.json"))

    def test_override_must_be_absolute(self):
        with self.assertRaises(ValueError):
            Settings(_env_file=None, bm25_vocabulary="relative/vocabulary.json")

    def test_missing_file_explains_how_to_build(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "absent.json"
            previous = os.environ.get("BM25_VOCABULARY")
            os.environ["BM25_VOCABULARY"] = str(missing)
            vocabulary.load_vocabulary.cache_clear()
            try:
                with self.assertRaisesRegex(
                    vocabulary.VocabularyMissingError, "build_bm25_vocabulary"
                ):
                    vocabulary.load_vocabulary()
            finally:
                if previous is None:
                    os.environ.pop("BM25_VOCABULARY", None)
                else:
                    os.environ["BM25_VOCABULARY"] = previous
                vocabulary.load_vocabulary.cache_clear()

    def test_fields_present(self):
        fields = vocabulary.load_vocabulary()["fields"]
        for name in ("ingredients", "keywords", "recipecategory", "extract_ingredients"):
            self.assertIn(name, fields)


if __name__ == "__main__":
    unittest.main()
