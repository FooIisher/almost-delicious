"""Offline schema and routing tests using synthetic JEV responses."""
import unittest

from jev_test import prepare, interpret
from intent_schema import INTENTS, extend_request, assemble, validate_context


class IntentRoutingTests(unittest.TestCase):
    def run_case(self, query, overrides, context=None, names=None):
        payload, ingredients, numbers = prepare(query, [])
        candidates = extend_request(payload, query, context, names)
        answers = {}
        defaults = {"intent": "recipe_search", "search_type": "name_search",
                    "question_type": "not_applicable", "meal_type": "not_stated"}
        for name, question in payload["questions"].items():
            if question["type"] == "boolean":
                answers[name] = {"type": "boolean", "probability": overrides.get(name, 0.01)}
            else:
                value = defaults.get(name, "not_stated" if name.startswith("available_") else
                                     "none" if name.startswith("ingredient_") else "other")
                value = overrides.get(name, value)
                answers[name] = {"type": "choice", "choice": value, "probabilities": {value: 0.99}}
        result = {"answers": answers}
        base = interpret(payload, result, ingredients, numbers, .8)
        return assemble(base, result, candidates, .8)

    def test_seven_routes(self):
        self.assertEqual(set(INTENTS), {"recipe_search", "meal_planning", "recipe_comparison",
                                       "recipe_how_to", "recipe_question_answering", "unsupported_request", "unknown"})

    def test_named_search(self):
        out = self.run_case("Taco Chicken", {"recipe_name_0": .99})
        self.assertEqual(out["recipe_names"], ["Taco Chicken"])
        self.assertEqual(out["status"], "ready")

    def test_quick_available_dinner(self):
        out = self.run_case("I have beef and potatoes. Suggest a quick dinner.", {
            "available_0": "available", "available_1": "available",
            "search_type": "constraint_search", "quick": .99, "meal_type": "dinner"})
        self.assertEqual(out["constraints"]["ingredients_available"], ["beef", "potato"])
        self.assertEqual(out["constraints"]["max_cooking_time_minutes"], 30)
        self.assertEqual(out["normalization"]["max_cooking_time_minutes"]["source"], "system_default")

    def test_explicit_time_is_not_overwritten(self):
        out = self.run_case("A quick dinner at most 45 minutes", {
            "search_type": "constraint_search", "quick": .99, "number_0": "upper_inclusive"})
        self.assertEqual(out["constraints"]["max_cooking_time_minutes"], 45)
        self.assertEqual(out["normalization"]["max_cooking_time_minutes"]["source"], "explicit_user_value")

    def test_planning_count_and_days(self):
        out = self.run_case("Plan two dinners", {"intent": "meal_planning", "extra_number_0": .99})
        self.assertEqual(out["constraints"]["number_of_recipes"], 2)
        self.assertEqual(out["status"], "ready")
        out = self.run_case("Create a three-day vegetarian meal plan", {
            "intent": "meal_planning", "extra_number_0": .99, "diet_vegetarian": .99})
        self.assertEqual(out["constraints"]["planning_days"], 3)
        out = self.run_case("Plan meals", {"intent": "meal_planning"})
        self.assertIn("number_of_recipes_or_planning_days", out["missing_fields"])

    def test_missing_and_selected_reference(self):
        settings = {"intent": "recipe_how_to", "question_type": "instructions"}
        out = self.run_case("How do I make this?", settings)
        self.assertIn("recipe_reference", out["missing_fields"])
        context = {"recipes": [{"id": "r1", "name": "Taco Chicken"}], "selected_recipe_id": "r1"}
        out = self.run_case("How do I make this?", dict(settings, reference_0=.99), context)
        self.assertEqual(out["recipe_references"], ["r1"])
        self.assertEqual(out["status"], "ready")

    def test_comparison_needs_targets_and_concrete_dimensions(self):
        out = self.run_case("Those two beef soups, which is healthier?", {
            "intent": "recipe_comparison", "compare_nutrition": .99, "unresolved_reference": .99})
        self.assertIn("recipe_references", out["missing_fields"])
        self.assertIn("comparison_dimensions", out["missing_fields"])
        context = {"recipes": [{"id": "a", "name": "Soup A"}, {"id": "b", "name": "Soup B"}]}
        out = self.run_case("Which of those two soups has more protein?", {
            "intent": "recipe_comparison", "compare_protein": .99,
            "reference_0": .99, "reference_1": .99}, context)
        self.assertEqual(out["status"], "ready")
        self.assertEqual(out["comparison_dimensions"], ["protein"])

    def test_recipe_qa(self):
        out = self.run_case("How many calories does Taco Chicken have?", {
            "intent": "recipe_question_answering", "question_type": "nutrition", "recipe_name_0": .99})
        self.assertEqual(out["status"], "ready")
        self.assertEqual(out["recipe_names"], ["Taco Chicken"])

    def test_abnormal_routes(self):
        out = self.run_case("Book a restaurant", {"intent": "unsupported_request"})
        self.assertEqual(out["status"], "unsupported")
        self.assertFalse(out["needs_clarification"])
        out = self.run_case("What about that?", {"intent": "unknown"})
        self.assertIn("user_goal", out["missing_fields"])

    def test_uncertainty_and_conflict(self):
        out = self.run_case("Taco Chicken", {"recipe_name_0": .6})
        self.assertEqual(out["recipe_names"], [])
        self.assertEqual(out["status"], "needs_clarification")
        out = self.run_case("Taco Chicken", {"recipe_name_0": .99, "conflicting_constraints": .99})
        self.assertIn("conflicting_constraints", out["clarification_reasons"])

    def test_invalid_context(self):
        with self.assertRaises(ValueError):
            validate_context({"recipes": [], "selected_recipe_id": "invented"})

    def test_search_does_not_require_existing_recipe(self):
        out = self.run_case("Suggest a dinner", {"unresolved_reference": .99})
        self.assertEqual(out["status"], "ready")
        self.assertEqual(out["unresolved_references"], [])

    def test_high_protein_is_not_an_invented_numeric_limit(self):
        out = self.run_case("Plan two high-protein dinners", {
            "intent": "meal_planning", "extra_number_0": .99, "prefer_high_protein": .99})
        self.assertIn("high_protein", out["constraints"]["soft_preferences"])
        self.assertIsNone(out["constraints"]["min_protein_g"])


if __name__ == "__main__":
    unittest.main()
