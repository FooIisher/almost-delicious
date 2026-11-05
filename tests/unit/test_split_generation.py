from tests.unit.recipe_fixture_names import distinct_recipe
import copy
import threading
import time
import unittest
from unittest.mock import patch
import recipe_search.llm.content_generation as service
from tests.unit import test_content_generation as legacy


class SplitGenerationTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp
    provider = legacy.ContentGenerationTests.provider

    def check(self, local=False, model="deepseek-flash"):
        return self.client.post(
            "/content/eligibility/" + model, json={**self.request, "local_only": local}
        )

    def summary(self, identifier, **kwargs):
        return self.client.post(
            "/content/generate/gpt41-mini", json=dict(eligibility_id=identifier, **kwargs)
        )

    def test_local_no_key_and_no_model(self):
        with (
            patch.dict("os.environ", OPENAI_API_KEY="", DEEPSEEK_API_KEY=""),
            patch.object(service.urllib.request, "urlopen") as provider,
        ):
            response = self.check(True)
        self.assertEqual(response.status_code, 200, response.text)
        provider.assert_not_called()
        self.assertEqual(response.json()["constraint_counts"]["not_checked"], 23)
        self.assertIsNone(response.json()["eligibility_id"])

    def test_local_fetch_failure_without_key_keeps_diagnostics(self):
        self.es.mget.side_effect = RuntimeError("Source fetch failed")
        with (
            patch.dict("os.environ", OPENAI_API_KEY="", DEEPSEEK_API_KEY=""),
            patch.object(service.urllib.request, "urlopen") as calls,
        ):
            r = self.check(True)
        self.assertEqual(r.status_code, 502, r.text)
        calls.assert_not_called()
        self.assertIn("Source fetch failed", r.json()["detail"]["message"])
        self.assertEqual(r.json()["detail"]["token_usage"]["call_count"], 0)

    def test_two_stages_models_cache_and_single_summary(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as calls:
            checked = self.check()
            self.assertEqual(checked.status_code, 200, checked.text)
            self.assertEqual(calls.call_count, 2)
            identifier = checked.json()["eligibility_id"]
            self.assertEqual(checked.json()["constraint_counts"]["pass"], 23)
            self.es.mget.reset_mock()
            with patch.object(
                service,
                "local_checks",
                side_effect=AssertionError("Summary must not rerun local checks"),
            ):
                result = self.summary(identifier, context=self.request)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(calls.call_count, 3)
            self.es.mget.assert_not_called()
            self.assertEqual(len(result.json()["model_calls"]), 1)
            self.assertEqual(result.json()["filter_model"], "deepseek-flash")
            again = self.check()
            self.assertTrue(again.json()["cache_hit"])
            self.assertEqual(calls.call_count, 3)
            self.assertEqual(again.json()["token_usage"]["call_count"], 0)
            self.assertEqual(again.json()["model_calls"], [])

    def test_target_parallel_stop_and_not_checked(self):
        docs = self.es.mget.return_value["docs"]
        self.es.mget.return_value["docs"] = [
            distinct_recipe({**copy.deepcopy(docs[0]), "_id": str(i)}) for i in range(100)
        ]
        self.request["recipe_ids"] = [str(i) for i in range(100)]
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as calls:
            r = self.check()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(r.json()["constraint_counts"]["pass"], 40)
        self.assertEqual(r.json()["constraint_counts"]["not_checked"], 60)
        self.assertEqual(r.json()["qualified_recipe_ids"], [str(i) for i in range(20)])

    def test_no_pass_skips_summary(self):
        self.change = (
            lambda out, p, c: [
                a["checks"][0].update(status="not_matched", evidence=[]) for a in out["assessments"]
            ]
            if c
            else None
        )
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as calls:
            r = self.check()
            self.assertEqual(r.status_code, 200, r.text)
            result = self.summary(r.json()["eligibility_id"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(result.json()["recommendations"], [])

    def test_expiry_bad_id_and_context_mismatch(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            r = self.check()
        identifier = r.json()["eligibility_id"]
        bad = copy.deepcopy(self.request)
        bad["retrieval_snapshot"]["exclude_ingredients"] = ["onion"]
        self.assertEqual(self.summary(identifier, context=bad).status_code, 409)
        self.assertEqual(self.summary("f" * 64).status_code, 409)
        now = time.monotonic()
        with patch.object(service.time, "monotonic", return_value=now + 1801):
            self.assertEqual(self.summary(identifier).status_code, 409)

    def test_data_model_conditions_and_versions_invalidate_key(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            first = self.check().json()["eligibility_id"]
            self.es.mget.return_value["docs"][0]["_source"]["ingredients"].append("carrot")
            second = self.check().json()["eligibility_id"]
            self.assertNotEqual(first, second)
            self.assertNotEqual(second, self.check(model="gpt41-nano").json()["eligibility_id"])
            with patch.object(service, "CHECK_PROMPT_VERSION", "new-prompt"):
                self.assertNotEqual(second, self.check().json()["eligibility_id"])
            self.request["retrieval_snapshot"]["exclude_ingredients"] = ["peanut"]
            self.assertNotEqual(second, self.check().json()["eligibility_id"])

    def test_default_summary_keeps_checked_pool_and_ignores_reclassification(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as call:
            identifier = self.check().json()["eligibility_id"]
            before = call.call_count

            def change(out, p, checking):
                if not checking:
                    self.assertFalse(p["semantic_recheck_enabled"])
                    self.assertTrue(p["recipes"][0]["previous_checks"])
                    self.assertTrue(all(not r["pending_checks"] for r in p["recipes"]))
                    out["assessments"][0]["checks"] = [
                        dict(
                            constraint_id="hard-1",
                            status="not_matched",
                            evidence=[],
                            reason="Attempt to reject a previously qualified recipe.",
                        )
                    ]

            self.change = change
            response = self.summary(identifier)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(call.call_count, before + 1)
            self.assertFalse(data["recheck_stats"]["enabled"])
            self.assertEqual(data["recheck_stats"]["overturned_count"], 0)
            self.assertEqual(data["constraint_counts"]["pass"], 23)
            self.assertIn("1", [r["recipe_id"] for r in data["recommendations"]])

    def test_recheck_off_and_overturn_does_not_change_cached_pool(self):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            identifier = self.check().json()["eligibility_id"]
            r = self.summary(identifier, recheck=False)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(all(not r["pending_checks"] for r in self.inputs[-1]["recipes"]))
            self.assertEqual(r.json()["recheck_stats"]["checked"], 0)

            def change(out, p, checking):
                if not checking:
                    out["assessments"][0]["checks"][0].update(status="not_matched", evidence=[])

            self.change = change
            r = self.summary(identifier, recheck=True)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(len(r.json()["recheck_stats"]["overturned"]), 1)
            self.assertEqual(r.json()["recheck_stats"]["overturned_count"], 1)
            self.assertAlmostEqual(r.json()["recheck_stats"]["overturn_rate"], 0.05)
            self.assertNotIn("1", [item["recipe_id"] for item in r.json()["recommendations"]])
            self.assertEqual(self.check().json()["constraint_counts"]["pass"], 23)

    def test_failed_batch_no_pool_all_dispatched_calls_recorded(self):
        self.change = lambda out, p, c: out.update(assessments=[]) if c else None
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as calls:
            r = self.check()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(calls.call_count, 2)
        self.assertTrue(r.json()["partial"])
        self.assertIsNone(r.json()["eligibility_id"])
        self.assertEqual(len(r.json()["model_calls"]), 2)
        self.assertEqual(len(r.json()["failed_batches"]), 2)

    def test_global_model_concurrency_at_most_two(self):
        active = 0
        peak = 0
        lock = threading.Lock()

        def provider(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.03)
                return self.provider(*args, **kwargs)
            finally:
                with lock:
                    active -= 1

        with patch.object(service.urllib.request, "urlopen", side_effect=provider):
            r = self.check()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(peak, 2)

    def test_cache_lru_capacity(self):
        c = service.EligibilityCache()
        for i in range(20):
            c.put(str(i), dict(value=i))
        c.get("0")
        c.put("20", dict(value=20))
        self.assertIsNotNone(c.get("0"))
        self.assertIsNone(c.get("1"))
        r = c.get("2")
        r["value"] = 99
        self.assertEqual(c.get("2")["value"], 2)
