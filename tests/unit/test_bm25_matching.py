import unittest
from recipe_search.matching.ingredient_match import ingredient_clause
from recipe_search.api.search import SearchRequest, bm25_query, build_filters


class BM25MatchingTests(unittest.TestCase):
    def test_boosts_do_not_change_lexical_eligibility_or_filters(self):
        request = SearchRequest(
            query="beef soup",
            bm25_dish_name="beef soup",
            bm25_dish_type="soup",
            bm25_cuisine="Mexican",
            bm25_categories=["Vegetabels", "vegetables"],
            include_ingredients=["beef"],
            exclude_ingredients=["onion"],
        )
        filters = build_filters(request)
        baseline = bm25_query(request.query, filters)["bool"]
        boosted = bm25_query(request.query, filters, request)["bool"]
        for field in ("must", "filter", "must_not"):
            self.assertEqual(baseline[field], boosted[field])
        self.assertEqual(boosted["minimum_should_match"], 0)
        self.assertEqual(request.bm25_categories, ["vegetable"])
        rewards = {
            clause["constant_score"]["_name"]: clause["constant_score"]
            for clause in boosted["should"]
        }
        self.assertEqual(
            rewards["dish_name_phrase"]["filter"], {"match_phrase": {"name": "beef soup"}}
        )
        self.assertNotIn("name.keyword", str(boosted))
        self.assertEqual(
            rewards["ingredient_category_0"]["filter"], {"terms": {"keywords": ["vegetable"]}}
        )
        self.assertEqual(rewards["required_ingredient_0"]["filter"], ingredient_clause("beef"))
        self.assertEqual(
            len([name for name in rewards if name.startswith("ingredient_category_")]), 1
        )
        self.assertEqual(rewards["dish_type"]["boost"], 5)
        self.assertEqual(rewards["cuisine"]["boost"], 6)

    def test_no_structured_inputs_only_title_phrase_bonus(self):
        request = SearchRequest(query="soup")
        query = bm25_query(request.query, None, request)["bool"]
        self.assertEqual(len(query["should"]), 1)
        self.assertEqual(
            query["should"][0]["constant_score"]["filter"], {"match_phrase": {"name": "soup"}}
        )

    def test_plural_group_rewarded_once_without_expanding_filters(self):
        request = SearchRequest(
            query="onion soup",
            include_ingredients=["onion", "onions"],
            bm25_categories=["beans", "vegetables"],
        )
        original = build_filters(request)
        query = bm25_query(request.query, original, request)["bool"]
        ingredient = [
            item["constant_score"]
            for item in query["should"]
            if item["constant_score"]["_name"].startswith("required_ingredient")
        ]
        self.assertEqual(len(ingredient), 1)
        self.assertEqual(ingredient[0]["filter"], ingredient_clause("onion"))
        self.assertEqual(query["filter"], original["bool"]["filter"])
