import io
import json
import socket
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import recipe_search.llm.content_generation as service
from tests.unit.recipe_fixture_names import distinct_recipe


class ContentGenerationTests(unittest.TestCase):
    def setUp(self):
        self.es = MagicMock()
        self.es.options.return_value = self.es
        self.es.mget.return_value = {
            "docs": [
                distinct_recipe(
                    {
                        "_id": str(i),
                        "found": True,
                        "_source": {
                            "ingredients": ["beef", "broccoli"],
                            "instructions": ["Original step."],
                            "keywords": ["soup"],
                            "content_vector": [9],
                        },
                    }
                )
                for i in range(1, 24)
            ]
        }
        extraction = dict(
            intent="recipe_search",
            search_text="soup",
            dish_name=None,
            dish_type="soup",
            meal_type=None,
            cuisine=None,
            target_evidence=dict(dish_name=None, dish_type="soup", meal_type=None, cuisine=None),
            ingredients=[
                dict(
                    name="vegetable", entity_type="category", role="required", evidence="vegetable"
                )
            ],
            bounds=[],
            dietary_restrictions=[],
            soft_preferences=[],
            corrections=[],
            clarification_questions=[],
        )
        self.request = dict(
            query="vegetable soup",
            intent_snapshot={
                "raw_query": "vegetable soup",
                "parsed": {"status": "ready", "extraction": extraction},
            },
            retrieval_snapshot={"query": "soup", "size": 1},
            recipe_ids=[str(i) for i in range(1, 24)],
        )
        self.inputs = []
        self.change = None
        app = FastAPI()
        app.include_router(service.create_router(lambda: self.es))
        self.client = TestClient(app)
        self.env = patch.dict("os.environ", OPENAI_API_KEY="test-key", DEEPSEEK_API_KEY="test-key")
        self.env.start()
        self.addCleanup(self.env.stop)
        self.save = patch.object(service, "save_failure", return_value=True)
        self.save.start()
        self.addCleanup(self.save.stop)

    def provider(self, call, **kwargs):
        body = json.loads(call.data)
        payload = json.loads(
            body["messages"][-1]["content"] if "messages" in body else body["input"]
        )
        self.inputs.append(payload)
        checking = "recommendation_limit" not in payload
        checks = []
        from recipe_search.matching.eligibility import phrase

        for recipe in payload["recipes"]:
            rows = []
            for c in recipe.get("pending_checks", payload["category_constraints"]):
                candidates = recipe["ingredients"]
                evidence = [
                    i
                    for i in candidates
                    if (
                        i == "broccoli"
                        if c["name"] == "vegetable"
                        else i == "beef"
                        if c["name"] == "meat"
                        else phrase(i, c["name"])
                    )
                ]
                rows.append(
                    dict(
                        constraint_id=c["constraint_id"],
                        status="matched"
                        if evidence
                        else "not_matched"
                        if candidates
                        else "unknown",
                        evidence=evidence,
                        reason="Recorded ingredient evidence.",
                    )
                )
            checks.append(dict(recipe_id=recipe["recipe_id"], checks=rows))
        output = dict(assessments=checks)
        if not checking:
            output.update(
                summary="Here are some options.",
                recommendations=[
                    dict(
                        recipe_id=r["recipe_id"],
                        reason="A soup with recorded ingredients.",
                        flavor="Not specified",
                        best_for="Soup",
                    )
                    for r in payload["recipes"][: payload["recommendation_limit"]]
                ],
            )
        if self.change:
            self.change(output, payload, checking)
        raw = {"model": "mock", "usage": {"total_tokens": 10}}
        if "messages" in body:
            raw["choices"] = [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]
        else:
            raw.update(
                status="completed",
                output=[
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(output)}],
                    }
                ],
            )
        return io.BytesIO(json.dumps(raw).encode())

    def run_request(self, model="gpt41-mini", stream=False, recheck=None):
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider) as call:
            if recheck is None:
                result = self.client.post(
                    "/content/generate/" + model + ("?stream=true" if stream else ""),
                    json=self.request,
                )
            else:
                checked = self.client.post("/content/eligibility/" + model, json=self.request)
                result = self.client.post(
                    "/content/generate/" + model,
                    json={"eligibility_id": checked.json()["eligibility_id"], "recheck": recheck},
                )
        return result, call

    def test_summary_without_hard_categories_is_bounded_and_source_steps_retained(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"]["instructions"] = ["Original step." * 10000]
        response, call = self.run_request("deepseek-flash")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.inputs), 1)
        self.assertEqual(len(self.inputs[0]["recipes"]), 20)
        self.assertNotIn("instructions", self.inputs[0]["recipes"][0])
        self.assertEqual(response.json()["recipes"][0]["instructions"], ["Original step." * 10000])

    def test_generation_keeps_display_metadata_out_of_model_payload(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        doc = self.es.mget.return_value["docs"][0]
        doc["_source"]["image_urls"] = ["https://example.test/photo.jpg"]
        response, call = self.run_request("deepseek-flash")
        self.assertEqual(response.status_code, 200, response.text)
        recipe = response.json()["recipes"][0]
        self.assertEqual(recipe["image_source"], "original")
        self.assertTrue(recipe["has_original_image"])
        self.assertIn("fallback_label", recipe)
        for record in self.inputs[0]["recipes"]:
            self.assertNotIn("image_urls", record)
            self.assertNotIn("display_image_url", record)

    def test_context_failure_keeps_prepared_input_and_other_batches(self):
        self.es.mget.return_value["docs"][0]["_source"]["ingredients"] = ["x" * 130000]
        response, call = self.run_request("deepseek-flash")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result["check_partial"])
        self.assertEqual(result["constraint_counts"]["pass"], 3)
        self.assertEqual(result["constraint_counts"]["not_checked"], 20)
        self.assertEqual(call.call_count, 2)
        self.assertTrue(
            all(r["recipe_id"] in ["21", "22", "23"] for r in result["recommendations"])
        )
        self.assertIsNotNone(service.save_failure.call_args.args[0]["model_input"])

    def test_mixed_cuisine_summary_does_not_claim_collective_match(self):
        self.request["retrieval_snapshot"].update(
            cuisine_target="Chinese", cuisine_role="required", dish_type_target="soup"
        )
        self.es.mget.return_value["docs"][0]["_source"]["keywords"] = ["Chinese", "soup"]
        self.es.mget.return_value["docs"][2]["_source"]["keywords"] = ["Japanese", "soup"]

        def change(out, p, checking):
            if not checking:
                out["summary"] = "These soups all fit a Chinese-inspired lunch."

        self.change = change
        response, _ = self.run_request()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["summary_grounding"]["adjusted"])
        self.assertNotIn("Chinese-inspired", response.json()["summary"])
        self.assertEqual(
            response.json()["summary"],
            "I found 5 recipes that best fit your request. See each recipe below for its individual matches.",
        )
        self.assertEqual(
            response.json()["summary_grounding"]["original_summary"],
            "These soups all fit a Chinese-inspired lunch.",
        )

    def test_summary_context_reduces_pool_without_truncating_ingredients(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"]["ingredients"] = ["x" * 10000]
        response, call = self.run_request()
        self.assertEqual(response.status_code, 200, response.text)
        sent = self.inputs[0]["recipes"]
        self.assertLess(len(sent), 20)
        self.assertEqual(sent[0]["ingredients"], ["x" * 10000])

    def test_four_models_batches_and_payload(self):
        for model in ("gpt41-mini", "gpt41-nano", "gpt6", "deepseek-flash"):
            self.inputs = []
            r, call = self.run_request(model)
            self.assertEqual(r.status_code, 200, r.text)
            d = r.json()
            self.assertEqual([len(p["recipes"]) for p in self.inputs], [20, 20])
            self.assertEqual(call.call_count, 2)
            self.assertEqual(
                d["constraint_counts"],
                {"pass": 20, "fail": 0, "unknown": 0, "not_checked": 3, "near_miss": 0},
            )
            self.assertEqual(len(d["recommendations"]), 5)
            self.assertEqual(d["usage"]["total_tokens"], 20)
            self.assertIn("pending_checks", self.inputs[0]["recipes"][0])
            self.assertNotIn("instructions", self.inputs[0]["recipes"][0])
            self.assertNotIn("content_vector", json.dumps(self.inputs))
            self.assertNotIn("test-key", r.text)
            self.assertEqual(d["recipes"][0]["instructions"], ["Original step."])

    def test_unknown_separate_and_fail_excluded(self):
        def change(out, p, checking):
            if checking:
                for a in out["assessments"]:
                    if a["recipe_id"] == "1":
                        a["checks"][0].update(status="unknown", evidence=[])
                    if a["recipe_id"] == "2":
                        a["checks"][0].update(status="not_matched", evidence=[])

        self.change = change
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["pending_recipe_ids"], ["1"])
        self.assertEqual(
            d["constraint_counts"],
            {"pass": 21, "fail": 1, "unknown": 1, "not_checked": 0, "near_miss": 0},
        )
        self.assertFalse({"1", "2"} & {r["recipe_id"] for r in d["recommendations"]})

    def test_all_unknown_or_failed_skip_summary(self):
        for status in ("unknown", "not_matched"):
            self.inputs = []
            self.change = (
                lambda out, p, c: [
                    a["checks"][0].update(status=status, evidence=[]) for a in out["assessments"]
                ]
                if c
                else None
            )
            r, call = self.run_request()
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(call.call_count, 2)
            self.assertEqual(r.json()["recommendations"], [])

    def test_missing_ingredients_unknown(self):
        self.es.mget.return_value["docs"][0]["_source"]["ingredients"] = []
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("1", r.json()["pending_recipe_ids"])

    def test_bad_coverage_evidence_ids_duplicate(self):
        for issue in ("missing", "duplicate", "evidence", "id"):

            def change(out, p, c):
                if not c:
                    return
                if issue == "missing":
                    out["assessments"].pop()
                if issue == "duplicate":
                    out["assessments"].append(out["assessments"][0])
                if issue == "evidence":
                    out["assessments"][0]["checks"][0]["evidence"] = ["invented"]
                if issue == "id":
                    out["assessments"][0]["recipe_id"] = "999"

            self.change = change
            r, call = self.run_request()
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(call.call_count, 2 if issue == "duplicate" else 3)
            if issue in ("missing", "id"):
                self.assertTrue(r.json()["check_partial"])
                self.assertTrue(r.json()["not_checked_recipe_ids"])
            if issue == "evidence":
                self.assertTrue(any("downgraded" in warning for warning in r.json()["warnings"]))
                self.assertIn("1", r.json()["pending_recipe_ids"])

    def test_late_batch_failure_keeps_diagnostics(self):
        def change(out, p, c):
            if len(self.inputs) == 2:
                out["assessments"] = []

        self.change = change
        r, call = self.run_request()
        self.assertEqual(r.status_code, 502)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(len(r.json()["detail"]["model_calls"]), 2)

    def test_no_hard_categories_single_call(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        r, call = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(call.call_count, 1)

    def test_excluded_category_filters_meat(self):
        c = self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"][0]
        c.update(name="meat", role="excluded")
        r, call = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["constraint_counts"]["fail"], 23)
        self.assertEqual(call.call_count, 2)

    def test_soft_roles_remain_nonblocking(self):
        for role in ("available", "prefer", "avoid"):
            self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"][0]["role"] = role
            r, call = self.run_request()
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(call.call_count, 1)

    def test_100_limit_and_missing_records(self):
        self.request["recipe_ids"] = [str(i) for i in range(101)]
        r, c = self.run_request()
        self.assertEqual(r.status_code, 422)
        c.assert_not_called()
        self.request["recipe_ids"] = ["1", "missing"]
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["input_recipe_count"], 1)
        self.assertTrue(r.json()["warnings"])

    def test_no_recipes_no_provider(self):
        self.es.mget.return_value = {"docs": []}
        r, c = self.run_request()
        self.assertEqual(r.status_code, 422)
        c.assert_not_called()

    def test_key_timeout_busy(self):
        with patch.dict("os.environ", OPENAI_API_KEY=""):
            r, c = self.run_request()
            self.assertEqual(r.status_code, 503)
            c.assert_not_called()
        with patch.object(service.urllib.request, "urlopen", side_effect=socket.timeout()):
            r = self.client.post("/content/generate/gpt41-mini", json=self.request)
            self.assertEqual(r.status_code, 504)
        with patch.object(service.SLOTS, "acquire", return_value=False):
            r, c = self.run_request()
            self.assertEqual(r.status_code, 503)
            c.assert_not_called()

    def test_stream_progress_and_failure(self):
        r, _ = self.run_request(stream=True)
        events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "result")
        self.assertTrue(any(e.get("completed") == 20 for e in events))
        self.change = lambda out, p, c: out.update(assessments=[]) if c else None
        r, _ = self.run_request(stream=True)
        self.assertIn('"type": "error"', r.text)
        self.assertNotIn('"type": "result"', r.text)

    def test_summary_cannot_select_failed_or_external_recipe(self):
        def change(out, p, c):
            if not c:
                out["recommendations"][0]["recipe_id"] = "999"

        self.change = change
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 502)

    def test_generated_steps_rejected(self):
        def change(out, p, c):
            if not c:
                out["recommendations"][0]["brief_instructions"] = ["invented"]

        self.change = change
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 502)

    def test_requested_count(self):
        self.request["query"] = "give 3 recipes of vegetable soup"
        self.request["intent_snapshot"]["raw_query"] = self.request["query"]
        r, _ = self.run_request()
        self.assertEqual(len(r.json()["recommendations"]), 3)

    def test_full_hundred_candidates_five_batches(self):
        docs = self.es.mget.return_value["docs"]
        template = docs[0]["_source"]
        self.es.mget.return_value = {
            "docs": [
                distinct_recipe({"_id": str(i), "found": True, "_source": template})
                for i in range(100)
            ]
        }
        self.request["recipe_ids"] = [str(i) for i in range(100)]
        r, c = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(c.call_count, 2)
        self.assertEqual([len(p["recipes"]) for p in self.inputs], [20] * 2)
        self.assertEqual(r.json()["constraint_counts"]["pass"], 20)
        self.assertEqual(r.json()["constraint_counts"]["not_checked"], 80)

    def test_missing_ingredient_cannot_be_absence(self):
        self.es.mget.return_value["docs"][0]["_source"]["ingredients"] = []

        def change(out, p, c):
            if c:
                out["assessments"][0]["checks"][0].update(status="not_matched", evidence=[])

        self.change = change
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 200)
        self.assertIn("1", r.json()["pending_recipe_ids"])

    def test_generation_usage_on_all_calls_and_failure(self):
        original = self.provider

        def priced(call, **kwargs):
            raw = json.loads(original(call, **kwargs).read())
            raw["model"] = "gpt-4.1-mini"
            raw["usage"] = {
                "input_tokens": 1000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 800},
                "total_tokens": 1100,
            }
            return io.BytesIO(json.dumps(raw).encode())

        self.provider = priced
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["token_usage"]["total_tokens"], 2200)
        self.assertAlmostEqual(d["cost_estimate"]["estimated_usd"], 0.00064)
        self.assertEqual(d["phase_usage"]["category_check"]["token_usage"]["total_tokens"], 1100)
        self.assertEqual(d["phase_usage"]["summary"]["token_usage"]["total_tokens"], 1100)
        self.change = (
            lambda out, p, c: out.update(assessments=[]) if len(self.inputs) == 2 else None
        )
        self.inputs = []
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["detail"]["token_usage"]["total_tokens"], 2200)

    def test_summary_rechecks_categories_and_updates_counts(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"][0].update(
            name="vegetable", role="excluded"
        )

        def change(out, p, checking):
            if checking:
                for a in out["assessments"]:
                    a["checks"][0].update(status="not_matched", evidence=[])
            else:
                self.assertEqual(p["category_constraints"][0]["role"], "excluded")
                self.assertIn("eligibility", p)
                out["recommendations"] = []

        self.change = change
        r, c = self.run_request(recheck=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(c.call_count, 3)
        self.assertEqual(r.json()["recommendations"], [])
        self.assertEqual(
            r.json()["constraint_counts"],
            {"pass": 3, "fail": 20, "unknown": 0, "not_checked": 0, "near_miss": 0},
        )

    def test_summary_cannot_warn_and_recommend_a_violation(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"][0]["role"] = (
            "excluded"
        )

        def change(out, p, checking):
            if checking:
                for a in out["assessments"]:
                    a["checks"][0].update(status="not_matched", evidence=[])
            else:
                out["recommendations"][0]["reason"] = (
                    "It contains vegetables, so it is not vegetable-free."
                )

        self.change = change
        r, _ = self.run_request(recheck=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["recommendations"], [])
        self.assertEqual(r.json()["selection_counts"]["filtered"], 5)

    def test_summary_unknown_is_not_a_formal_recommendation(self):
        def change(out, p, checking):
            if not checking:
                out["assessments"][0]["checks"][0].update(status="unknown", evidence=[])

        self.change = change
        r, _ = self.run_request(recheck=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("1", [item["recipe_id"] for item in r.json()["recommendations"]])
        self.assertIn("1", r.json()["pending_recipe_ids"])
        self.assertEqual(r.json()["selection_counts"]["filtered"], 1)

    def test_semantic_membership_in_both_prompts(self):
        for prompt in (service.CHECK_PROMPT, service.PROMPT):
            self.assertIn("SEMANTIC membership, not literal keyword matching", prompt)
            self.assertIn("onion, onions, carrots and celery", prompt)
            self.assertIn("absence of the category word is NEVER evidence", prompt)

    def test_only_summary_candidate_all_rejected_is_successful_empty(self):
        self.request["recipe_ids"] = ["1"]
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"][0]["role"] = (
            "excluded"
        )

        def change(out, p, checking):
            if checking:
                for a in out["assessments"]:
                    a["checks"][0].update(status="not_matched", evidence=[])

        self.change = change
        r, c = self.run_request(recheck=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(c.call_count, 2)
        self.assertEqual(r.json()["recommendations"], [])
        self.assertEqual(
            r.json()["constraint_counts"],
            {"pass": 0, "fail": 1, "unknown": 0, "not_checked": 0, "near_miss": 0},
        )
        self.assertNotIn("Here are some options", r.json()["summary"])

    def test_generation_keeps_edited_scope_snapshot(self):
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"]["keywords"] = ["lunch", "italian"]
        self.request["retrieval_snapshot"].update(
            meal_type_target="lunch",
            cuisine_target="italian",
            cuisine_role="required",
            preference_available=["salmon"],
            bm25_available_boost=3,
        )
        r, _ = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        summary = self.inputs[-1]["preferences"]
        self.assertEqual(summary["meal_type_target"], "lunch")
        self.assertEqual(summary["cuisine_target"], "italian")
        self.assertNotIn("bm25_available_boost", summary)
        self.assertNotIn("retrieval_trace", self.inputs[-1])
        self.assertEqual(r.json()["execution_snapshot"]["retrieval"]["bm25_available_boost"], 3)

    def test_meal_required_is_explanation_only(self):
        extraction = self.request["intent_snapshot"]["parsed"]["extraction"]
        extraction.update(ingredients=[], meal_type="lunch", meal_type_role="required")
        extraction["target_evidence"]["meal_type"] = "lunch"
        self.request["retrieval_snapshot"].update(meal_type_target="lunch")
        r, c = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(c.call_count, 1)
        self.assertTrue(r.json()["recommendations"])
        self.assertFalse(any(x["kind"] == "meal_type" for x in r.json()["category_constraints"]))

    def test_broad_unknown_cuisine_cannot_recommend(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(cuisine_target="italian", cuisine_role="required")

        def change(out, p, checking):
            if checking:
                for a in out["assessments"]:
                    for c in a["checks"]:
                        c.update(
                            status="unknown", evidence=[], reason="Cuisine cannot be confirmed."
                        )

        self.change = change
        r, c = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["constraint_counts"]["unknown"], 23)
        self.assertEqual(r.json()["recommendations"], [])
        self.assertTrue(all("interpretation" not in p for p in self.inputs))

    def test_dish_target_cuisine_is_soft(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(
            cuisine_target="italian", cuisine_role="required", dish_type_target="soup"
        )
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"]["keywords"] = ["soup"]
        r, c = self.run_request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(c.call_count, 1)
        self.assertFalse(any(x["kind"] == "cuisine" for x in r.json()["category_constraints"]))
