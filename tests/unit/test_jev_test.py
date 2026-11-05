"""Offline contract tests; mocked answers do not measure model accuracy."""

import unittest

from recipe_search.llm.jev.jev_test import prepare, interpret


class IngredientExtractionTests(unittest.TestCase):
    def parse(self, text, roles, availability, probabilities=None):
        payload, ingredients, numbers = prepare(text, [])
        answers = {
            "intent": {
                "type": "choice",
                "choice": "recipe_search",
                "probabilities": {"recipe_search": 0.99},
            },
            "needs_clarification": {"type": "boolean", "probability": 0.01},
        }
        for i, ingredient in enumerate(ingredients):
            for prefix, value in [
                ("ingredient", roles.get(ingredient, "none")),
                ("available", availability.get(ingredient, "not_stated")),
            ]:
                name = f"{prefix}_{i}"
                answers[name] = {
                    "type": "choice",
                    "choice": value,
                    "probabilities": {value: (probabilities or {}).get(name, 0.99)},
                }
        self.assertFalse(numbers)
        return interpret(payload, {"answers": answers}, ingredients, numbers, 0.8)

    def test_available_dinner_ingredients(self):
        result = self.parse(
            "I have beef and potato, can you give a suggestion for a quick dinner",
            {},
            {"beef": "available", "potato": "available"},
        )
        self.assertEqual(result["fields"]["available_ingredients"], ["beef", "potato"])
        self.assertEqual(result["fields"]["include_ingredients"], [])
        self.assertEqual(result["fields"]["exclude_ingredients"], [])
        self.assertEqual(result["ingredient_preferences"], [])
        self.assertIsNone(result["fields"]["max_total_time_minutes"])

    def test_availability_can_overlap_with_requirement(self):
        result = self.parse(
            "I have beef. Use beef and potatoes, without peanuts.",
            {"beef": "include", "potato": "include", "peanut": "exclude"},
            {"beef": "available"},
        )
        self.assertEqual(result["fields"]["available_ingredients"], ["beef"])
        self.assertEqual(result["fields"]["include_ingredients"], ["beef", "potato"])
        self.assertEqual(result["fields"]["exclude_ingredients"], ["peanut"])

    def test_available_but_excluded(self):
        result = self.parse(
            "I have beef but do not use it.", {"beef": "exclude"}, {"beef": "available"}
        )
        self.assertEqual(result["fields"]["available_ingredients"], ["beef"])
        self.assertEqual(result["fields"]["exclude_ingredients"], ["beef"])

    def test_unavailable_is_not_forbidden(self):
        result = self.parse(
            "I have no beef. I would prefer potatoes.",
            {"potato": "preference"},
            {"beef": "not_available"},
        )
        self.assertEqual(result["fields"]["available_ingredients"], [])
        self.assertEqual(result["fields"]["exclude_ingredients"], [])
        self.assertEqual(result["ingredient_preferences"], ["potato"])

    def test_uncertain_availability_is_not_promoted(self):
        result = self.parse("I might have beef.", {}, {"beef": "available"}, {"available_0": 0.6})
        self.assertEqual(result["fields"]["available_ingredients"], [])
        self.assertTrue(result["needs_clarification"])
        self.assertIn("available_0", result["uncertain_questions"])
        result = self.parse("I might have beef.", {}, {"beef": "unclear"})
        self.assertTrue(result["needs_clarification"])


if __name__ == "__main__":
    unittest.main()
