import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "extraction"))

from rules import Extractor, norm  # noqa: E402


class ExtractionRuleTests(unittest.TestCase):
    def setUp(self):
        self.extractor = Extractor(["egg", "berries", "butter", "brown sugar", "onion"])

    def extract(self, parts, instructions, quantities=None):
        return self.extractor.extract("1", parts, quantities or [""] * len(parts), instructions)

    def test_reports_unlisted_terms_with_evidence(self):
        record = self.extract(["butter"], ["Toss 2 cups berries with sugar."])
        self.assertEqual(record["extract_ingredients"], ["berry"])
        self.assertEqual(record["extract_evidence"][0]["text"], "Toss 2 cups berries with sugar.")
        self.assertFalse(record["extract_evidence"][0]["hedged"])
        self.assertEqual(record["extraction_version"], "rule-v1")

    def test_listed_ingredients_and_stop_words_are_skipped(self):
        record = self.extract(["eggs", "onions"], ["Beat the egg, add onion, salt and water."])
        self.assertEqual(record["extract_ingredients"], [])

    def test_supplement_and_hedging(self):
        record = self.extract(["egg"], ["Serve with orange juice if desired."])
        self.assertEqual(record["extract_ingredients"], ["orange juice"])
        self.assertTrue(record["extract_evidence"][0]["hedged"])

    def test_equipment_context_is_ignored(self):
        record = self.extract(["egg"], ["Grease a butter dish."])
        self.assertEqual(record["extract_ingredients"], [])

    def test_incomplete_list_flag_and_norm(self):
        record = self.extract(["egg"], [], quantities=["1", "2"])
        self.assertTrue(record["ingredient_list_incomplete"])
        self.assertEqual(norm("Leaves and Berries"), "leaf and berry")


if __name__ == "__main__":
    unittest.main()
