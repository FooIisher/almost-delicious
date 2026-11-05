import os
import math
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import intent_service as service
from recipe_search_api import app


def gateway(overrides=None):
    """Return schema-shaped synthetic answers; never used by the application."""
    overrides = overrides or {}

    def evaluate(payload, key, timeout):
        defaults = {"intent": "recipe_search", "search_type": "name_search",
                    "question_type": "not_applicable", "meal_type": "not_stated"}
        answers = {}
        for name, question in payload["questions"].items():
            if question["type"] == "boolean":
                answers[name] = {"type": "boolean", "probability": overrides.get(name, .01)}
            else:
                value = defaults.get(name, "not_stated" if name.startswith("available_") else
                                     "none" if name.startswith("ingredient_") else "other")
                value = overrides.get(name, value)
                answers[name] = {"type": "choice", "choice": value, "probabilities": {value: .99}}
        return {"answers": answers, "usage": {"input_tokens": 10, "output_tokens": 10}}
    return evaluate


class IntentServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def parse(self, query, overrides=None, **body):
        with patch.object(service.jev, "evaluate", side_effect=gateway(overrides)):
            response = self.client.post("/intent/parse", json={"query": query, **body})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_preserves_query_versions_and_schema_output(self):
        result = self.parse("  Taco Chicken  ", {"recipe_name_0": .99})
        self.assertEqual(result["raw_query"], "  Taco Chicken  ")
        self.assertEqual(result["query"], "Taco Chicken")
        self.assertEqual(result["parsed"]["recipe_names"], ["Taco Chicken"])
        self.assertEqual(result["model"], "typesafe-ai/jev")
        self.assertEqual(result["provider"], "vercel_gateway")
        self.assertEqual(result["parsed"]["search_text"], "Taco Chicken")
        self.assertEqual(result["search_text_source"], "original_query")
        self.assertTrue(result["warnings"])
        self.assertEqual(result["corrections"], [])
        self.assertTrue(result["prompt_version"])
        self.assertTrue(result["schema_version"])
        self.assertFalse(result["filters_applied"])
        self.assertGreaterEqual(result["intent_parse_ms"], 0)
        self.assertNotIn("API_KEY", str(result))

    def test_all_seven_routes_are_retained(self):
        for intent in service.schema.INTENTS:
            with self.subTest(intent=intent):
                result = self.parse("Taco Chicken", {"intent": intent})
                self.assertEqual(result["parsed"]["intent"], intent)
                self.assertEqual(result["execution_support"] == "supported", intent == "recipe_search")

    def test_inventory_is_not_a_required_ingredient_and_quick_is_labeled(self):
        result = self.parse("I have beef and potatoes. Suggest a quick dinner.", {
            "available_0": "available", "available_1": "available",
            "search_type": "constraint_search", "quick": .99, "meal_type": "dinner"})
        self.assertEqual(result["parsed"]["constraints"]["ingredients_available"], ["beef", "potato"])
        self.assertEqual(result["parsed"]["constraints"]["ingredients_required"], [])
        default = next(row for row in result["constraint_rows"] if row["source"] == "system_default")
        self.assertEqual(default["value"], 30)
        self.assertTrue(default["needs_confirmation"])
        self.assertTrue(all(row["applied"] is False for row in result["constraint_rows"]))

    def test_strict_bounds_and_unsupported_filters_are_visible(self):
        result = self.parse("Find vegetarian dinner under 30 minutes", {
            "search_type": "constraint_search", "number_0": "upper_exclusive", "diet_vegetarian": .99})
        strict = next(row for row in result["constraint_rows"] if row["operator"] == "<")
        self.assertEqual(strict["value"], 30)
        self.assertEqual(strict["support"], "unsupported")
        diet = next(row for row in result["constraint_rows"] if row["field"] == "dietary_restrictions")
        self.assertEqual(diet["support"], "unsupported")

    def test_unit_normalization_explicit_bound(self):
        result = self.parse("Find dinner at most 1 hour", {"number_0": "upper_inclusive"})
        bound = next(row for row in result["constraint_rows"] if row["field"] == "max_cooking_time_minutes")
        self.assertEqual((bound["operator"], bound["value"], bound["unit"]), ("≤", 60, "min"))
        self.assertFalse(bound["needs_confirmation"])

    def test_context_references_and_missing_references(self):
        query = "How do I make this?"
        missing = self.parse(query, {"intent": "recipe_how_to", "question_type": "instructions"})
        self.assertTrue(missing["parsed"]["needs_clarification"])
        result = self.parse(query, {"intent": "recipe_how_to", "question_type": "instructions", "reference_0": .99},
            context={"recipes": [{"id": "123", "name": "Soup"}], "selected_recipe_id": "123"})
        self.assertEqual(result["parsed"]["recipe_references"], ["123"])

    def test_conflicts_are_not_presented_as_ready(self):
        result = self.parse("Find chicken", {"conflicting_constraints": .99})
        self.assertEqual(result["parsed"]["status"], "needs_clarification")
        self.assertIn("conflicting_constraints", result["parsed"]["clarification_reasons"])

    def test_bad_request_never_calls_model(self):
        for body in ({"query": "   "}, {"query": "x" * 501}, {"query": "x", "context": {"selected_recipe_id": "fake"}}):
            with patch.object(service.jev, "evaluate") as call:
                self.assertEqual(self.client.post("/intent/parse", json=body).status_code, 422)
                call.assert_not_called()

    def test_invalid_model_output_is_not_exposed_as_success(self):
        for raw in ({}, {"answers": {}}, {"answers": {"intent": {"type": "choice", "probabilities": {"recipe_search": math.nan}}}}):
            with patch.object(service.jev, "evaluate", return_value=raw):
                response = self.client.post("/intent/parse", json={"query": "chicken"})
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()["detail"]["code"], "invalid_model_output")

    def test_all_displayed_probabilities_are_validated(self):
        def malformed(payload, key, timeout):
            raw = gateway()(payload, key, timeout)
            raw["answers"]["intent"]["probabilities"]["meal_planning"] = -1
            return raw
        with patch.object(service.jev, "evaluate", side_effect=malformed):
            response = self.client.post("/intent/parse", json={"query": "chicken"})
        self.assertEqual(response.status_code, 502)

    def test_gateway_failure_redacts_key_and_timeout_is_explicit(self):
        with patch.dict(service.os.environ, {"JEV_API_KEY": "fake-secret"}), \
             patch.object(service.jev, "evaluate", side_effect=ValueError("HTTP 401: fake-secret")):
            response = self.client.post("/intent/parse", json={"query": "chicken"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("fake-secret", response.text)
        with patch.object(service.jev, "evaluate", side_effect=ValueError("Network connection failed or request timed out.")):
            response = self.client.post("/intent/parse", json={"query": "chicken"})
        self.assertEqual(response.status_code, 504)

    def test_capacity_error_and_missing_configuration(self):
        with patch.object(service, "PARSE_SLOTS") as slots:
            slots.acquire.return_value = False
            response = self.client.post("/intent/parse", json={"query": "chicken"})
        self.assertEqual(response.status_code, 503)
        with patch.dict(service.os.environ, {"JEV_API_KEY": ""}), patch.object(service.jev, "DEFAULT_API_KEY", ""):
            response = self.client.post("/intent/parse", json={"query": "chicken"})
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
