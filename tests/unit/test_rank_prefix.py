import copy
import unittest
from unittest.mock import patch

import recipe_search.llm.content_generation as service
from tests.unit import test_content_generation as legacy
from tests.unit.recipe_fixture_names import distinct_recipe


class RankedPrefixTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp
    provider = legacy.ContentGenerationTests.provider

    def setup_mixed(self, pending_ids):
        docs = self.es.mget.return_value["docs"]
        template = copy.deepcopy(docs[0])
        self.es.mget.return_value["docs"] = [
            distinct_recipe({**copy.deepcopy(template), "_id": str(i)}) for i in range(1, 61)
        ]
        self.request["recipe_ids"] = [str(i) for i in range(1, 61)]
        original = service.local_checks

        def local(recipe, constraints):
            checks = original(recipe, constraints)
            if recipe["recipe_id"] not in pending_ids:
                for c in checks:
                    if c["kind"] == "category":
                        c.update(
                            status="matched",
                            decision="pass",
                            source="local",
                            semantic_required=False,
                            evidence=["broccoli"],
                        )
            return checks

        return patch.object(service, "local_checks", side_effect=local)

    def test_local_twenty_passes_cannot_skip_earlier_pending(self):
        with (
            self.setup_mixed({"1", "40"}),
            patch.object(service.urllib.request, "urlopen") as model,
        ):
            r = self.client.post(
                "/content/eligibility/deepseek-flash", json={**self.request, "local_only": True}
            )
        self.assertEqual(r.status_code, 200, r.text)
        model.assert_not_called()
        d = r.json()
        self.assertFalse(d["auto_completed"])
        self.assertIsNone(d["eligibility_id"])
        self.assertEqual(d["eligibility_stats"]["frontier_rank"], 21)
        self.assertEqual(d["eligibility_stats"]["pending_prefix_recipe_ids"], ["1"])

    def test_only_pending_before_frontier_is_sent(self):
        with (
            self.setup_mixed({"1", "40"}),
            patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as model,
        ):
            r = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(self.inputs[0]["expected_recipe_ids"], ["1"])
        d = r.json()
        self.assertEqual(d["qualified_recipe_ids"], [str(i) for i in range(1, 21)])
        self.assertEqual(d["eligibility_stats"]["frontier_rank"], 20)
        self.assertTrue(d["eligibility_stats"]["prefix_complete"])
        self.assertEqual(
            next(a for a in d["assessments"] if a["recipe_id"] == "40")["status"], "not_checked"
        )

    def test_frontier_recomputed_after_wave_and_tail_never_sent(self):
        pending = {str(i) for i in range(1, 26)} | {"50"}
        with (
            self.setup_mixed(pending),
            patch.object(service.urllib.request, "urlopen", side_effect=self.provider),
        ):
            r = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
        self.assertEqual(r.status_code, 200, r.text)
        submitted = {i for payload in self.inputs for i in payload["expected_recipe_ids"]}
        self.assertEqual(submitted, {str(i) for i in range(1, 26)})
        self.assertEqual(r.json()["eligibility_stats"]["frontier_rank"], 20)
        self.assertEqual(r.json()["qualified_recipe_ids"], [str(i) for i in range(1, 21)])

    def test_failed_prefix_cannot_publish_local_pass_pool(self):
        self.change = (
            lambda out, payload, checking: out.update(assessments=[]) if checking else None
        )
        with (
            self.setup_mixed({"1", "40"}),
            patch.object(service.urllib.request, "urlopen", side_effect=self.provider),
        ):
            r = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIsInstance(d["eligibility_id"], str)
        self.assertTrue(d["partial"])
        self.assertFalse(d["coverage_complete"])
        self.assertFalse(d["eligibility_stats"]["prefix_complete"])
        self.assertEqual(d["failed_batches"][0]["recipe_ids"], ["1"])

    def test_definite_unknown_is_concluded_not_pending(self):
        recipes = [{"recipe_id": str(i)} for i in range(22)]
        prior = {r["recipe_id"]: dict(status="pass", checks=[]) for r in recipes}
        prior["0"] = dict(status="unknown", checks=[dict(semantic_required=False)])
        result = service.qualified_prefix(recipes, prior, 20)
        self.assertTrue(result["prefix_complete"])
        self.assertEqual(result["frontier_rank"], 21)

    def test_model_reorder_is_recorded_without_overriding_choice(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.change = (
            lambda out, payload, checking: out["recommendations"].reverse()
            if not checking
            else None
        )
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            checked = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
            r = self.client.post(
                "/content/generate/deepseek-flash",
                json={"eligibility_id": checked.json()["eligibility_id"]},
            )
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d["recommendation_order"]["reordered"])
        self.assertEqual(
            d["recommendation_order"]["model_order"], [x["recipe_id"] for x in d["recommendations"]]
        )
