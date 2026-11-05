import copy
import unittest
from unittest.mock import patch

import recipe_search.llm.content_generation as service
from recipe_search.llm.extraction_schema import Extraction
from recipe_search.llm.generation_recovery import final_summary, index_assessments
from recipe_search.matching.core_policy import apply_core_policy
from recipe_search.matching.eligibility import constraints_for, local_checks
from recipe_search.retrieval.relaxation_planner import alternative_groups, assess_candidate
from tests.unit import test_content_generation as legacy
from tests.unit.test_multi_relaxation import leaf, plans, request


class SummaryRecoveryTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp
    provider = legacy.ContentGenerationTests.provider

    def test_blank_summary_falls_back_for_each_provider_without_retry(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        for model in ["gpt41-mini", "gpt41-nano", "gpt6", "deepseek-flash"]:
            for summary in ["", "  \n "]:
                with self.subTest(model=model, summary=summary):
                    self.change = lambda out, p, c: out.update(summary=summary) if not c else None
                    with patch.object(
                        service.urllib.request, "urlopen", side_effect=self.provider
                    ) as calls:
                        response = self.client.post("/content/generate/" + model, json=self.request)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertTrue(response.json()["summary"].strip())
                    self.assertEqual(calls.call_count, 1)
                    self.assertEqual(len(response.json()["recommendations"]), 5)

    def test_null_summary_still_invalid_structure(self):
        with self.assertRaises(ValueError):
            service.GeneratedContent.model_validate(
                dict(summary=None, assessments=[], recommendations=[])
            )

    def test_tradeoff_intro_does_not_concatenate_diagnostic_reasons(self):
        from types import SimpleNamespace

        items = [SimpleNamespace(recipe_id=str(i)) for i in range(3)]
        prior = {
            "0": {
                "deviations": [
                    dict(kind="ingredient", name="beef", reason="No beef in recorded...")
                ]
            },
            "1": {
                "deviations": [dict(kind="ingredient", name="pineapple", reason="No pineapple...")]
            },
            "2": {
                "deviations": [
                    dict(
                        kind="numeric",
                        name="total_time",
                        operator="lt",
                        reason="Total Time: 20 min; 5 min above...",
                    )
                ]
            },
        }
        summary = final_summary("", 0, items, prior)
        self.assertIn("without beef", summary)
        self.assertIn("without pineapple", summary)
        self.assertIn("more cooking time", summary)
        self.assertNotIn("Total Time:", summary)
        self.assertNotIn("recorded...", summary)


class AssessmentRecoveryTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp
    provider = legacy.ContentGenerationTests.provider

    def check(self):
        return self.client.post("/content/eligibility/deepseek-flash", json=self.request)

    def test_all_integer_or_padded_ids_and_identical_duplicates_are_recovered(self):
        def mutate(out, p, c):
            if not c:
                return
            for index, row in enumerate(out["assessments"]):
                row["recipe_id"] = (
                    int(row["recipe_id"]) if index % 2 else " " + row["recipe_id"] + " "
                )
            out["assessments"].append(copy.deepcopy(out["assessments"][0]))
            out["assessments"].append(dict(recipe_id="outside", checks=[]))

        self.change = mutate
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as calls:
            result = self.check()
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertFalse(data["partial"])
        self.assertEqual(data["constraint_counts"]["pass"], 23)
        self.assertEqual(calls.call_count, 2)
        self.assertTrue(any("unknown recipe" in w for w in data["warnings"]))

    def test_only_missing_and_conflicting_recipe_fail(self):
        def mutate(out, p, c):
            if not c:
                return
            if p["expected_recipe_ids"][0] == "1":
                out["assessments"] = [a for a in out["assessments"] if a["recipe_id"] != "1"]
                duplicate = copy.deepcopy(out["assessments"][0])
                duplicate["checks"][0]["status"] = "unknown"
                out["assessments"].append(duplicate)

        self.change = mutate
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            result = self.check()
        data = result.json()
        self.assertTrue(data["partial"])
        self.assertEqual(data["constraint_counts"]["pass"], 21)
        self.assertEqual(data["failed_batches"][0]["recipe_ids"], ["1", "2"])
        self.assertEqual(data["constraint_counts"]["not_checked"], 2)

    def test_partial_subset_can_generate_and_retry_does_not_mutate_snapshot(self):
        def mutate(out, p, c):
            if c:
                out["assessments"] = [a for a in out["assessments"] if a["recipe_id"] != "1"]

        self.change = mutate
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            data = self.check().json()
        self.assertTrue(data["partial"])
        self.assertTrue(data["eligibility_id"])
        self.assertNotEqual(data["eligibility_id"], data["check_run_id"])
        original_ids = data["qualified_recipe_ids"]
        self.change = None
        self.inputs = []
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as calls:
            summary = self.client.post(
                "/content/generate/deepseek-flash", json={"eligibility_id": data["eligibility_id"]}
            )
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(calls.call_count, 1)
        self.assertTrue(summary.json()["check_partial"])
        self.assertNotIn("1", self.inputs[0]["expected_recipe_ids"])
        self.assertEqual(self.inputs[0]["expected_recipe_ids"], original_ids)
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            retried = self.client.post(
                "/content/eligibility/deepseek-flash",
                json={
                    **self.request,
                    "retry_run_id": data["check_run_id"],
                    "retry_batch_ids": [data["failed_batches"][0]["batch_id"]],
                },
            )
            old = self.client.post(
                "/content/generate/deepseek-flash", json={"eligibility_id": data["eligibility_id"]}
            )
        self.assertFalse(retried.json()["partial"])
        self.assertTrue(old.json()["check_partial"])
        self.assertIn("1", old.json()["not_checked_recipe_ids"])

    def test_no_valid_assessments_do_not_publish_partial_pool(self):
        self.change = lambda out, p, c: out.update(assessments=[]) if c else None
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            data = self.check().json()
        self.assertTrue(data["partial"])
        self.assertIsNone(data["eligibility_id"])
        self.assertFalse(data["generation_ready"])

    def test_indexed_output_can_be_recovered_without_guessing_unknown_ids(self):
        indexed, warnings = index_assessments(
            {"1": {"checks": []}, "other": {"checks": []}}, ["1", "2"]
        )
        self.assertEqual(len(indexed["1"]), 1)
        self.assertEqual(indexed["2"], [])
        self.assertTrue(warnings)


class CorePolicyTests(unittest.TestCase):
    def extraction(self, query, dish="stir fry", names=("beef", "onion"), expression="AND"):
        from recipe_search.matching.constraint_logic import RequiredExpression as E

        data = dict(
            intent="recipe_search",
            search_text=dish,
            dish_name=dish,
            dish_type="stir fry",
            meal_type=None,
            cuisine=None,
            target_evidence=dict(
                dish_name=dish, dish_type="stir fry", meal_type=None, cuisine=None
            ),
            ingredients=[
                dict(name=n, entity_type="specific", role="required", evidence=n, core=True)
                for n in names
            ],
            required_expression=(
                E(op=expression, children=[leaf(n) for n in names]).model_dump()
                if len(names) > 1
                else leaf(names[0]).model_dump()
            ),
            bounds=[],
            dietary_restrictions=[],
            soft_preferences=[],
            corrections=[],
            clarification_questions=[],
        )
        return apply_core_policy(Extraction.model_validate(data), query)

    def test_plain_with_and_and_time_emphasis_do_not_protect_ingredients(self):
        p = self.extraction("stir fry with beef and onion and it must finish in 15 minutes")
        self.assertFalse(any(i.core for i in p.ingredients))
        self.assertEqual(p._core_reasons, {})

    def test_named_dish_emphasis_sole_and_or_remain_distinct(self):
        p = self.extraction(
            "pineapple beef stir fry with onion",
            dish="pineapple beef stir fry",
            names=("pineapple", "beef", "onion"),
        )
        self.assertEqual([i.core for i in p.ingredients], [True, True, False])
        self.assertEqual(p._core_reasons["beef"], "dish_identity")
        p = self.extraction("stir fry must have beef, with onion")
        self.assertTrue(p.ingredients[0].core)
        self.assertFalse(p.ingredients[1].core)
        p = self.extraction("stir fry with beef", names=("beef",))
        self.assertEqual(p._core_reasons["beef"], "sole_required")
        p = self.extraction("stir fry with beef or onion", expression="OR")
        self.assertFalse(any(i.core for i in p.ingredients))


class DeviationPresentationTests(unittest.TestCase):
    def test_strict_numeric_equality_never_says_zero_above(self):
        for op in ["lt", "gt"]:
            r = request(
                numeric_filters=[
                    dict(field="total_time", operator=op, value=15, basis="not_applicable")
                ]
            )
            conditions, expr = constraints_for(r, None)
            plan = plans(r)[0]
            recipe = dict(ingredients=["beef"], total_time_minutes=15)
            result = assess_candidate(
                "x",
                local_checks(recipe, conditions),
                dict(source_level="relaxed", relaxation=plan["actions"]),
                expr,
            )
            self.assertEqual(result["status"], "near_miss")
            self.assertIn("Exactly 15", result["deviations"][0]["reason"])
            self.assertNotIn("0 min above", result["deviations"][0]["reason"])
        r = request(max_total_time_minutes=15)
        conditions, expr = constraints_for(r, None)
        self.assertEqual(
            assess_candidate("x", local_checks(dict(total_time_minutes=15), conditions), {}, expr)[
                "status"
            ],
            "pass",
        )

    def test_group_title_does_not_repeat_subsumed_dish_type(self):
        r = request(
            include_ingredients=["durian"],
            required_expression=leaf("durian"),
            dish_name_target="fruit salad",
            dish_type_target="salad",
        )
        constraints, expr = constraints_for(r, None)
        recipe = dict(
            recipe_id="1",
            name="Fruit Salad",
            ingredients=["banana"],
            keywords=["salad"],
            recipecategory=[],
        )
        a = assess_candidate(
            "1",
            local_checks(recipe, constraints),
            dict(source_level="relaxed", relaxation=plans(r)[0]["actions"]),
            expr,
        )
        group = alternative_groups([recipe], {"1": a})[0]
        self.assertIn("fruit salad", group["title"])
        self.assertNotIn("fruit salad, salad", group["title"])


if __name__ == "__main__":
    unittest.main()
