import unittest
from unittest.mock import patch

from pydantic import ValidationError
from recipe_search.api.search import SearchRequest, build_filters, retrieve_candidates


class NumericFilterTests(unittest.TestCase):
    def test_operators_units_and_multi_bound_range(self):
        for operator in ("lt", "lte", "gt", "gte", "eq"):
            request = SearchRequest(
                query="soup",
                numeric_filters=[
                    dict(field="total_time", operator=operator, value=30, basis="not_applicable"),
                    dict(field="calories", operator="lt", value=500, basis="per_serving"),
                    dict(field="protein", operator="gte", value=20, basis="per_serving"),
                ],
            )
            filters = build_filters(request)["bool"]["filter"]
            expected = {"gte": 30, "lte": 30} if operator == "eq" else {operator: 30}
            self.assertIn({"range": {"total_time_minutes": expected}}, filters)
            self.assertIn({"range": {"calories": {"lt": 500}}}, filters)
            self.assertIn({"range": {"proteincontent": {"gte": 20}}}, filters)
            self.assertIn({"exists": {"field": "calories"}}, filters)
        request = SearchRequest(
            query="soup",
            numeric_filters=[
                dict(field="total_time", operator="gte", value=15, basis="not_applicable"),
                dict(field="total_time", operator="lt", value=30, basis="not_applicable"),
            ],
        )
        self.assertEqual(len(build_filters(request)["bool"]["filter"]), 6)

    def test_unconfirmed_basis_and_invalid_values_rejected(self):
        for changes in (
            {"basis": "unspecified"},
            {"basis": "whole_recipe"},
            {"basis": "per_day"},
            {"value": -1},
            {"value": float("nan")},
            {"operator": "between"},
        ):
            condition = dict(field="calories", operator="lt", value=500, basis="per_serving")
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                SearchRequest(query="soup", numeric_filters=[{**condition, **changes}])

    def test_legacy_maximum_controls_remain_inclusive(self):
        filters = build_filters(
            SearchRequest(query="soup", max_calories=500, max_total_time_minutes=30)
        )
        self.assertIn({"range": {"calories": {"lte": 500}}}, filters["bool"]["filter"])
        self.assertIn(
            {"range": {"total_time_minutes": {"gt": 0, "lte": 30}}}, filters["bool"]["filter"]
        )

    def test_both_branches_receive_identical_numeric_filters(self):
        import recipe_search.api.search as api

        request = SearchRequest(
            query="soup",
            numeric_filters=[
                dict(field="total_time", operator="lt", value=30, basis="not_applicable")
            ],
        )
        filters = build_filters(request)
        with (
            patch.object(api, "get_client") as client,
            patch.object(api, "get_model"),
            patch.object(api, "encode_query", return_value=[0.1]),
        ):
            client.return_value.options.return_value = client.return_value
            client.return_value.search.return_value = {
                "hits": {"hits": [], "total": {"value": 0, "relation": "eq"}},
                "took": 0,
            }
            retrieve_candidates(request, filters, "bm25")
            lexical = client.return_value.search.call_args.kwargs
            retrieve_candidates(request, filters, "vector")
            vector = client.return_value.search.call_args.kwargs
        lexical_body = lexical.get("body", lexical)
        vector_body = vector.get("body", vector)
        self.assertEqual(lexical_body["query"]["bool"]["filter"], filters["bool"]["filter"])
        self.assertEqual(vector_body["knn"]["filter"], filters)
