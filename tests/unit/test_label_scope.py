"""The old label scope contract is explicitly retired."""

import unittest
from unittest.mock import patch
from pydantic import ValidationError
import recipe_search.api.search as api
from tests.unit.test_search import FakeES
from recipe_search.matching.eligibility import constraints_for, local_checks, decision


class LabelScopeTests(unittest.TestCase):
    def test_old_scope_is_rejected(self):
        for kwargs in (
            {"retrieval_strategy": "label_scope"},
            {"scope_meal_types": ["lunch"]},
            {"scope_cuisines": ["italian"]},
        ):
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(ValidationError, "Label scope is retired"),
            ):
                api.SearchRequest(query="soup", **kwargs)

    def test_targets_never_filter_recall(self):
        r = api.SearchRequest(
            query="salmon",
            cuisine_target="italian",
            cuisine_role="required",
            meal_type_target="lunch",
            bm25_cuisine="italian",
            bm25_meal_type="lunch",
        )
        self.assertEqual(api.build_filters(r), {"bool": {"filter": [], "must_not": []}})
        q = api.bm25_query(r.query, None, r)["bool"]
        self.assertIn("multi_match", q["must"][0])
        self.assertEqual(q["minimum_should_match"], 0)
        self.assertIn("cuisine", str(q["should"]))
        self.assertIn("meal_type", str(q["should"]))

    def test_only_broad_required_cuisine_is_final(self):
        for dish, role, count in [("", "required", 1), ("soup", "required", 0), ("", "prefer", 0)]:
            r = api.SearchRequest(
                query="italian",
                dish_type_target=dish,
                cuisine_target="italian",
                cuisine_role=role,
                meal_type_target="lunch",
            )
            c, _ = constraints_for(r, None)
            self.assertEqual(sum(x["kind"] == "cuisine" for x in c), count)
            self.assertFalse(any(x["kind"] == "meal_type" for x in c))

    def test_independent_queries_and_trace(self):
        r = api.SearchRequest(
            bm25_query="salmon pasta",
            vector_query="Italian salmon lunch",
            vector_scope_query="Italian lunch",
            execution="serial",
        )
        es = FakeES()
        with (
            patch.object(api, "get_client", return_value=es),
            patch.object(api, "get_model"),
            patch.object(api, "encode_weighted", return_value=[0.1]) as weighted,
        ):
            data = api.search(r)
        weighted.assert_called_once()
        self.assertEqual(
            data["executed_queries"]["vector"][0]["semantic_scope_query"], "Italian lunch"
        )
        self.assertEqual(len(es.calls), 2)

    def test_cuisine_needs_confirmed_evidence(self):
        r = api.SearchRequest(query="lunch", cuisine_target="italian", cuisine_role="required")
        c, e = constraints_for(r, None)
        for tags, state in [(["italian"], "pass"), ([], "unknown")]:
            result = decision(
                "1",
                local_checks(
                    dict(name="Lunch", ingredients=["chicken"], keywords=tags, recipecategory=[]), c
                ),
                e,
            )
            self.assertEqual(result["status"], state)
