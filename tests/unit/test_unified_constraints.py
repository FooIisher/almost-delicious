from tests.unit.recipe_fixture_names import distinct_recipe
import json
import unittest
from unittest.mock import patch
from pydantic import ValidationError
import recipe_search.api.search as api
import recipe_search.llm.content_generation as generation
from recipe_search.matching.constraint_logic import RequiredExpression as E, evaluate
from recipe_search.matching.eligibility import (
    constraints_for,
    local_checks,
    decision,
    apply_semantic,
)
from tests.unit import test_content_generation as harness
from tests.unit.test_rrf import hit


def leaf(name):
    return E(op="ingredient", ingredient=name)


def group(op, *nodes):
    return E(op=op, children=list(nodes))


class UnifiedConstraintTests(unittest.TestCase):
    def test_three_valued_groups(self):
        expr = group(
            "AND",
            group("OR", leaf("beef"), leaf("chicken")),
            group("OR", leaf("potatoes"), leaf("rice")),
        )
        self.assertEqual(
            evaluate(expr, dict(beef="fail", chicken="pass", potatoes="unknown", rice="pass")),
            "pass",
        )
        self.assertEqual(
            evaluate(expr, dict(beef="fail", chicken="unknown", rice="fail", potatoes="fail")),
            "fail",
        )
        self.assertEqual(
            evaluate(expr, dict(beef="fail", chicken="unknown", rice="pass")), "unknown"
        )

    def test_satisfied_or_does_not_report_unused_unknown_as_pending(self):
        r = api.SearchRequest(
            query="soup",
            include_ingredients=["beef", "chicken"],
            required_expression=group("OR", leaf("beef"), leaf("chicken")),
        )
        c, e = constraints_for(r, None)
        d = decision(
            "a",
            local_checks(
                dict(name="Soup", ingredients=["beef"], keywords=[], recipecategory=[]), c
            ),
            e,
        )
        self.assertEqual(d["status"], "pass")
        self.assertEqual(d["unresolved"], [])
        self.assertTrue(d["checks"][1]["alternative_not_needed"])

    def test_invalid_expression_references_and_shape(self):
        for name in ("invented", "onion"):
            with self.assertRaises(ValidationError):
                api.SearchRequest(
                    query="soup",
                    include_ingredients=["beef"],
                    exclude_ingredients=["onion"],
                    required_expression=leaf(name),
                )
        self.assertEqual(E(op="AND", children=[leaf("beef")]).op, "ingredient")

    def test_safe_category_projection_and_legacy_or(self):
        mixed = group("AND", group("OR", leaf("beef"), leaf("vegetable")), leaf("rice"))
        r = api.SearchRequest(
            query="soup",
            required_expression=mixed,
            include_ingredients=["beef", "rice"],
            category_required=["vegetable"],
            exclude_ingredients=["onion"],
        )
        filters = json.dumps(api.build_filters(r))
        self.assertIn("arborio rice", filters)
        self.assertNotIn("beef tenderloin", filters)
        self.assertNotIn("vegetable broth", filters)
        self.assertIn("onion powder", filters)
        legacy = api.SearchRequest(query="soup", include_ingredients=["beef", "chicken"])
        self.assertIn("minimum_should_match", json.dumps(api.build_filters(legacy)))

    def test_local_evidence_aliases_and_numeric_phrase(self):
        r = api.SearchRequest(
            query="soup",
            include_ingredients=["chicken"],
            exclude_ingredients=["onion"],
            dish_name_target="Chicken Soup",
            numeric_filters=[
                dict(field="total_time", operator="lte", value=15, basis="not_applicable")
            ],
        )
        constraints, expr = constraints_for(r, None)
        recipe = dict(
            name="Quick CHICKEN, soup!",
            ingredients=["chicken broth", "onion powder"],
            keywords=[],
            recipecategory=[],
            total_time_minutes=15,
        )
        checks = local_checks(recipe, constraints)
        d = decision("1", checks, expr)
        self.assertEqual(d["status"], "fail")
        self.assertEqual(checks[0]["decision"], "pass")
        self.assertEqual(checks[1]["decision"], "fail")
        self.assertEqual(checks[-1]["decision"], "pass")
        recipe["ingredients"] = ["chicken broth", "seasoning blend"]
        checks = local_checks(recipe, constraints)
        self.assertEqual(checks[1]["decision"], "pass")
        self.assertTrue(checks[1]["assumed_absent"])

    def test_local_groups_do_not_become_soft_on_relaxation(self):
        r = api.SearchRequest(
            query="soup",
            include_ingredients=["beef", "potato"],
            required_expression=group("AND", leaf("beef"), leaf("potato")),
        )
        c, e = constraints_for(r, None)
        self.assertEqual(
            decision(
                "a",
                local_checks(
                    dict(name="Beef soup", ingredients=["beef"], keywords=[], recipecategory=[]), c
                ),
                e,
            )["status"],
            "unknown",
        )

    def test_shared_statistics_failure_preserves_original_conditions(self):
        calls = []

        def retrieve(request, filters, branch):
            calls.append((request, filters))
            return dict(hits=[hit("1")], timings={}, total=None)

        r = api.SearchRequest(
            query="soup",
            mode="bm25",
            include_ingredients=["beef", "rice"],
            exclude_ingredients=["onion"],
            required_expression=group("AND", leaf("beef"), leaf("rice")),
        )
        with (
            patch.object(api, "get_client", side_effect=TimeoutError),
            patch.object(api, "retrieve_candidates", side_effect=retrieve),
        ):
            result = api.search(r)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["results"][0]["recipe_id"], "1")
        self.assertEqual(calls[0][0].exclude_ingredients, ["onion"])
        self.assertEqual(result["relaxation"]["status"], "statistics_failed")

    def test_category_evidence_cannot_be_title_or_keyword(self):
        r = api.SearchRequest(query="soup", category_required=["vegetable"])
        constraints, expr = constraints_for(r, None)
        recipe = dict(
            name="Vegetable soup", ingredients=["beef"], keywords=["vegetable"], recipecategory=[]
        )
        checks = local_checks(recipe, constraints)
        assessment = generation.Assessment(
            recipe_id="1",
            checks=[
                generation.CategoryCheck(
                    constraint_id=constraints[0]["constraint_id"],
                    status="matched",
                    evidence=["Vegetable soup"],
                    reason="Title evidence",
                )
            ],
        )
        warnings = apply_semantic(assessment, recipe, checks, checks)
        self.assertEqual(checks[0]["decision"], "unknown")
        self.assertTrue(warnings)

    def test_exclude_only_never_relaxes(self):
        with patch.object(
            api, "retrieve_candidates", return_value=dict(hits=[hit("1")], timings={}, total=None)
        ) as retrieve:
            result = api.search(
                api.SearchRequest(query="soup", mode="bm25", exclude_ingredients=["onion"])
            )
        self.assertEqual(retrieve.call_count, 1)
        self.assertFalse(result["bm25_fallback"]["triggered"])


class AdaptiveEligibilityTests(unittest.TestCase):
    setUp = harness.ContentGenerationTests.setUp
    provider = harness.ContentGenerationTests.provider
    run_request = harness.ContentGenerationTests.run_request

    # Inherited baseline tests intentionally exercise the same four-model harness.
    def test_group_fail_cannot_be_recommended_and_no_summary_call(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(
            include_ingredients=["beef", "rice"],
            required_expression=group("AND", leaf("beef"), leaf("rice")).model_dump(),
        )
        r, call = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["recommendations"], [])
        self.assertEqual(call.call_count, 2)
        self.assertEqual(r.json()["constraint_counts"]["fail"], 23)

    def test_requested_over_twenty_and_not_checked(self):
        template = self.es.mget.return_value["docs"][0]["_source"]
        self.es.mget.return_value = {
            "docs": [
                distinct_recipe(dict(_id=str(i), found=True, _source=template)) for i in range(100)
            ]
        }
        self.request["recipe_ids"] = [str(i) for i in range(100)]
        self.request["query"] = "give 30 recipes of vegetable soup"
        self.request["intent_snapshot"]["raw_query"] = self.request["query"]
        r, c = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["eligibility_stats"]["processed"], 40)
        self.assertEqual(d["constraint_counts"]["not_checked"], 60)
        self.assertEqual(d["eligibility_stats"]["target"], 30)

    def test_empty_numeric_data_unknown_not_model_inferred(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"]["numeric_filters"] = [
            dict(field="total_time", operator="lte", value=15, basis="not_applicable")
        ]
        r, c = self.run_request()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["constraint_counts"]["unknown"], 23)
        c.assert_not_called()
