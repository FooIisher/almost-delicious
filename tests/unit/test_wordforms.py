import unittest
from unittest.mock import patch
from recipe_search.matching.wordforms import candidates, matching_forms, distinct_groups


class WordformTests(unittest.TestCase):
    def test_rules_and_exceptions(self):
        for value, expected in [
            ("onion", "onions"),
            ("onions", "onion"),
            ("potato", "potatoes"),
            ("potatoes", "potato"),
            ("leaf", "leaves"),
            ("leaves", "leaf"),
            ("chicken breasts", "chicken breast"),
            ("berry", "berries"),
        ]:
            self.assertIn(expected, candidates(value))
        for value in ("fish", "asparagus", "seafood", "greens", "couscous", "molasses"):
            self.assertEqual(candidates(value), {value})

    def test_field_vocabulary_gates_variants_and_unknown_keeps_original(self):
        words = {"keywords": {"onions"}, "ingredients": {"onion", "onions", "potato", "potatoes"}}
        with patch("recipe_search.matching.wordforms.vocabulary", return_value=words):
            self.assertEqual(matching_forms("keywords", "Onion"), ["onions"])
            self.assertEqual(matching_forms("ingredients", "onions"), ["onion", "onions"])
            self.assertEqual(matching_forms("keywords", "unknown"), ["unknown"])
            self.assertEqual(
                distinct_groups("ingredients", ["onion", "onions"]), [["onion", "onions"]]
            )

    def test_actual_snapshot(self):
        self.assertEqual(matching_forms("keywords", "onion"), ["onions"])
        self.assertEqual(matching_forms("keywords", "vegetables"), ["vegetable"])
        self.assertEqual(
            matching_forms("ingredients", "chicken breast"), ["chicken breast", "chicken breasts"]
        )
