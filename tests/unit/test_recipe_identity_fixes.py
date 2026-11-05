import unittest
from unittest.mock import patch

import recipe_search.llm.content_generation as service
from recipe_search.llm.content_generation import Assessment, CategoryCheck
from recipe_search.matching.eligibility import apply_semantic, local_checks
from recipe_search.matching.ingredient_match import ingredient_clause
from recipe_search.matching.ingredient_sources import classify_usage
from tests.unit import test_content_generation as legacy


def constraint(kind="dish_name", name="beef noodle soup", role="required"):
    return dict(constraint_id="hard-1", kind=kind, name=name, role=role)


def recipe(**extra):
    return dict(
        name="Oriental Beef and Noodle Soup",
        ingredients=["beef"],
        extract_ingredients=["rice"],
        keywords=[],
        recipecategory=[],
        **extra,
    )


class IdentityAndProvenanceTests(unittest.TestCase):
    def test_name_reordering_plural_and_connectors(self):
        for name in [
            "Oriental Beef and Noodle Soup",
            "Beef, Noodles & Soup",
            "Soup with noodles and beef",
        ]:
            checks = local_checks(dict(recipe(), name=name), [constraint()])
            self.assertEqual(checks[0]["decision"], "pass", name)

    def test_name_missing_or_negated_is_pending(self):
        for name in ["Vegetable soup", "Noodle soup without beef", "Beef-free noodle soup", ""]:
            c = local_checks(dict(recipe(), name=name), [constraint()])[0]
            self.assertEqual(c["decision"], "unknown")
            self.assertTrue(c["semantic_required"])

    def test_name_semantic_can_confirm_or_reject(self):
        for status, expected in [("matched", "pass"), ("not_matched", "fail")]:
            r = recipe()
            r["name"] = "Oriental soup"
            c = local_checks(r, [constraint()])
            a = Assessment(
                recipe_id="1",
                checks=[
                    CategoryCheck(
                        constraint_id="hard-1",
                        status=status,
                        evidence=["Oriental soup"],
                        reason="Dish identity reviewed.",
                    )
                ],
            )
            apply_semantic(a, r, c, c[:])
            self.assertEqual(c[0]["decision"], expected)

    def test_serving_never_required_but_still_excluded(self):
        r = recipe(extract_evidence=[dict(ingredient="rice", text="Serve with rice.")])
        for role, state in [("required", "fail"), ("excluded", "fail")]:
            c = local_checks(r, [constraint("ingredient", "rice", role)])[0]
            self.assertEqual(c["decision"], state)
            self.assertEqual(c["evidence_sources"][0]["usage"], "serving_optional")

    def test_preparation_and_legacy_unknown(self):
        r = recipe()

        def c():
            return local_checks(r, [constraint("ingredient", "rice")])[0]

        self.assertEqual(c()["decision"], "unknown")
        r["extract_evidence"] = [dict(ingredient="rice", text="Add rice and simmer.")]
        self.assertEqual(c()["decision"], "pass")
        r["ingredients"].append("rice")
        r["extract_evidence"] = [dict(ingredient="rice", text="Serve with rice.")]
        self.assertEqual(c()["decision"], "pass")

    def test_semantic_cannot_promote_unknown_or_serving_mentions(self):
        for evidence, expected in [
            ([], "unknown"),
            ([dict(ingredient="rice", text="Serve with rice.")], "fail"),
        ]:
            r = recipe(extract_evidence=evidence)
            c = local_checks(r, [constraint("category", "grain")])
            a = Assessment(
                recipe_id="1",
                checks=[
                    CategoryCheck(
                        constraint_id="hard-1",
                        status="matched",
                        evidence=["rice"],
                        reason="Rice is a grain.",
                    )
                ],
            )
            apply_semantic(a, r, c, c[:])
            self.assertEqual(c[0]["decision"], expected)

    def test_clause_roles_and_usage_classification(self):
        self.assertIn("extract_ingredients_firm", str(ingredient_clause("rice")))
        self.assertNotIn("extract_ingredients_firm", str(ingredient_clause("rice", excluded=True)))
        self.assertEqual(classify_usage("Serve with steamed rice."), "serving_optional")
        self.assertEqual(classify_usage("Add rice and boil."), "preparation")
        self.assertEqual(classify_usage("A note about rice."), "unknown")
        self.assertEqual(
            classify_usage("Add chicken and serve with rice.", ingredient="chicken"), "preparation"
        )
        self.assertEqual(
            classify_usage("Add chicken and serve with rice.", ingredient="rice"),
            "serving_optional",
        )
        self.assertEqual(classify_usage("Do not add rice.", ingredient="rice"), "unknown")

    def test_unknown_context_can_be_resolved_by_model_but_not_name_alone(self):
        r = recipe(
            extract_evidence=[dict(ingredient="rice", text="The rice was simmered until tender.")]
        )
        c = local_checks(r, [constraint("ingredient", "rice")])
        self.assertEqual(c[0]["decision"], "unknown")
        a = Assessment(
            recipe_id="1",
            checks=[
                CategoryCheck(
                    constraint_id="hard-1",
                    status="matched",
                    evidence=["rice"],
                    reason="Recorded context describes preparing the rice.",
                )
            ],
        )
        apply_semantic(a, r, c, c[:])
        self.assertEqual(c[0]["decision"], "pass")
        self.assertEqual(c[0]["evidence_sources"][0]["usage_confirmed_by_model"], "preparation")

    def test_absence_warning(self):
        c = local_checks(recipe(), [constraint("ingredient", "onion", "excluded")])[0]
        self.assertIn("does not establish allergy safety", c["reason"])


class LocalCompletionTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp
    provider = legacy.ContentGenerationTests.provider

    def test_local_ready_for_all_models_no_calls_then_summary(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        for model in ["deepseek-flash", "gpt41-mini", "gpt41-nano", "gpt6"]:
            with patch.object(service.urllib.request, "urlopen") as calls:
                r = self.client.post(
                    "/content/eligibility/" + model, json={**self.request, "local_only": True}
                )
            self.assertEqual(r.status_code, 200, r.text)
            calls.assert_not_called()
            d = r.json()
            self.assertTrue(d["auto_completed"])
            self.assertEqual(d["constraint_counts"]["pass"], 23)
            self.assertEqual(len(d["qualified_recipe_ids"]), 20)
            with patch.object(
                service.urllib.request, "urlopen", side_effect=self.provider
            ) as calls:
                result = self.client.post(
                    "/content/generate/gpt41-mini", json={"eligibility_id": d["eligibility_id"]}
                )
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(calls.call_count, 1)
            payload = self.inputs[-1]
            self.assertNotIn("interpretation", payload)
            self.assertNotIn("retrieval", payload)
            self.assertNotIn("retrieval_trace", payload)
            self.assertTrue(all("instructions" not in row for row in payload["recipes"]))
            self.assertIn("input_sections_bytes", result.json()["model_calls"][0])

    def test_below_target_does_not_publish_local_pool(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["recipe_ids"] = ["1"]
        with patch.object(service.urllib.request, "urlopen") as calls:
            r = self.client.post(
                "/content/eligibility/deepseek-flash", json={**self.request, "local_only": True}
            )
        calls.assert_not_called()
        self.assertIsNone(r.json()["eligibility_id"])
        self.assertFalse(r.json()["auto_completed"])
