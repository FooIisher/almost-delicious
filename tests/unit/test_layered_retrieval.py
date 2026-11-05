import unittest
from unittest.mock import patch
import numpy as np
import recipe_search.api.search as api
from recipe_search.matching.ingredient_match import matches, expand
from recipe_search.retrieval.query_builder import build_queries
from recipe_search.retrieval.search_recipes import encode_weighted, encode_query
from recipe_search.matching.tag_expansion import tag_matches
from tests.unit.test_search import candidates
from tests.unit.test_rrf import hit


class LayeredTests(unittest.TestCase):
    def test_ingredient_rules(self):
        for name, ingredient, expected in [
            ("egg", "eggs", True),
            ("egg", "eggplant", False),
            ("milk", "buttermilk", True),
            ("milk", "unsweetened coconut milk", False),
            ("chicken", "salt-free chicken broth", True),
            ("egg", "egg-free mayonnaise", False),
            ("onion", "onion powder", True),
            ("onion", "scallions", True),
            ("tea", "steak", False),
            ("nut", "butternut squash", False),
        ]:
            with self.subTest(name=name, ingredient=ingredient):
                self.assertEqual(matches(name, ingredient), expected)
        self.assertEqual(expand("onion"), expand("onions"))
        self.assertNotIn("eggplant", expand("egg"))

    def test_positive_query(self):
        for text, expected in [
            ("no-bake chocolate dessert", "no-bake chocolate dessert"),
            ("no-knead bread", "no-knead bread"),
            ("gluten-free cake", "gluten-free cake"),
            ("chicken soup without onion and garlic but with carrots", "chicken soup with carrots"),
        ]:
            q = build_queries({"search_text": text})
            self.assertEqual(q["vector_query"], expected)
        self.assertEqual(build_queries({"search_text": "no onion"})["vector_query"], "")

    def test_vector_main_separates_scope(self):
        q = build_queries(
            {
                "search_text": "spicy Chinese soup for lunch",
                "cuisine": "Chinese",
                "meal_type": "lunch",
                "dish_type": "soup",
            }
        )
        self.assertNotIn("Chinese", q["vector_query"])
        self.assertNotIn("lunch", q["vector_query"])
        self.assertIn("Chinese", q["vector_scope_query"])

    def test_empty_exclusion_warns_and_never_sends_empty_terms(self):
        request = api.SearchRequest(
            query="soup", mode="bm25", exclude_ingredients=["nonexistentingredientxyz"]
        )
        self.assertNotIn("'ingredients': []", str(api.build_filters(request)))
        with patch.object(api, "retrieve_candidates", return_value=candidates([hit(1)])):
            result = api.search(request)
        self.assertEqual(result["unapplied_exclusions"], ["nonexistentingredientxyz"])
        self.assertTrue(any("No ES exclusion" in warning for warning in result["warnings"]))
        self.assertNotIn("retrieval_strategy", result["original_conditions"])

    def test_spicy_soup_and_identical_scope(self):
        a = build_queries(
            {
                "search_text": "spicy Chinese soup",
                "dish_type": "soup",
                "cuisine": "Chinese",
                "meal_type": "lunch",
            }
        )
        self.assertEqual(a["bm25_query"], "spicy soup")
        self.assertIn("lunch", a["vector_scope_query"])
        b = build_queries(
            {"search_text": "Chinese dinner", "cuisine": "Chinese", "meal_type": "dinner"}
        )
        self.assertEqual(b["vector_scope_query"], "")
        self.assertTrue(b["warnings"])

    def test_scope_restores_omitted_meal(self):
        q = build_queries(
            {
                "search_text": "spicy Chinese soup",
                "cuisine": "Chinese",
                "meal_type": "lunch",
                "dish_type": "soup",
            }
        )
        self.assertIn("lunch", q["vector_scope_query"])
        self.assertEqual(q["vector_scope_query"].lower().count("chinese"), 1)

    def test_dish_type_name_shared_rule(self):
        from recipe_search.matching.dish_match import dish_type_evidence

        self.assertEqual(
            dish_type_evidence("soup", "Spicy Roasted Red Pepper Soup", []),
            ["Spicy Roasted Red Pepper Soup"],
        )
        self.assertEqual(dish_type_evidence("soup", "Soupy cake", []), [])

    def test_query_scope_and_or(self):
        e = {
            "ingredients": [
                {"name": "beef", "role": "required", "entity_type": "specific"},
                {"name": "chicken", "role": "required", "entity_type": "specific"},
            ],
            "required_expression": {
                "op": "OR",
                "children": [
                    {"op": "ingredient", "ingredient": "beef"},
                    {"op": "ingredient", "ingredient": "chicken"},
                ],
            },
        }
        q = build_queries(
            {"dish_type": "soup", "search_text": "Mexican soup with beef or chicken"}, e
        )
        self.assertEqual(q["bm25_query"], "soup")
        self.assertEqual(q["vector_scope_query"], "")
        self.assertIn("Mexican", q["vector_query"])

    def test_weighted_encoding(self):
        class Model:
            def encode(self, text, **kw):
                return (
                    np.array([1.0, 0.0])
                    if isinstance(text, str)
                    else np.array([[1.0, 0.0], [0.0, 1.0]])
                )

        model = Model()
        self.assertEqual(encode_weighted(model, "a", "b", beta=0), encode_query(model, "a"))
        vector = encode_weighted(model, "a", "b", beta=0.3)
        self.assertAlmostEqual(np.linalg.norm(vector), 1)
        self.assertAlmostEqual(vector[1] / vector[0], 0.3)

    def test_meal_max_not_sum(self):
        found, weight = tag_matches("meal_types", "dinner", ["weeknight", "one dish meal"])
        self.assertEqual(len(found), 2)
        self.assertEqual(weight, 0.35)
        query = api.bm25_query(
            "soup", None, api.SearchRequest(query="soup", bm25_meal_type="dinner")
        )
        dismax = next(c["dis_max"] for c in query["bool"]["should"] if "dis_max" in c)
        self.assertEqual(dismax["tie_breaker"], 0)

    def test_single_modes_candidate_depth_and_disable_rerank(self):
        for mode in ("bm25", "vector", "hybrid"):
            r = api.SearchRequest(query="soup", mode=mode, apply_preference_rerank=False)
            with patch.object(
                api, "retrieve_candidates", return_value=candidates([hit(i) for i in range(130)])
            ):
                result = api.search(r)
            self.assertEqual(len(result["generation_candidate_ids"]), 100)
            self.assertEqual(len(result["results"]), 20)

    def test_shared_statistics_failure_does_not_run_old_stage_fallback(self):
        e = {
            "op": "AND",
            "children": [
                {"op": "ingredient", "ingredient": "beef"},
                {"op": "ingredient", "ingredient": "rice"},
            ],
        }
        with (
            patch.object(api, "get_client", side_effect=TimeoutError),
            patch.object(
                api, "retrieve_candidates", return_value=candidates([hit(i) for i in range(3)])
            ) as retrieve,
        ):
            result = api.search(
                api.SearchRequest(
                    query="soup",
                    mode="bm25",
                    include_ingredients=["beef", "rice"],
                    required_expression=e,
                )
            )
        self.assertEqual(retrieve.call_count, 1)
        self.assertEqual(result["relaxation"]["status"], "statistics_failed")
