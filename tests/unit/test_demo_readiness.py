import os
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

from fastapi.testclient import TestClient

import recipe_search.api.search as api
from recipe_search.api.app import app as application
from recipe_search.llm.content_generation import CHECK_PROMPT, ingredient_relaxation_notes


class WarmupTests(unittest.TestCase):
    def test_warmup_is_bounded_local_vector_read(self):
        with (
            patch.dict(os.environ, RECIPE_WARMUP="1"),
            patch.object(
                api,
                "retrieve_candidates",
                return_value={"hits": [], "timings": {"query_embedding_ms": 12}},
            ) as query,
        ):
            api.warmup_retrieval()
        request, filters, branch = query.call_args.args
        self.assertEqual(branch, "vector")
        self.assertEqual(request.vector_candidates, 5)
        self.assertEqual(request.vector_num_candidates, 100)
        self.assertEqual(api.WARMUP_STATE["status"], "complete")

    def test_warmup_failure_does_not_abort_service(self):
        with (
            patch.dict(os.environ, RECIPE_WARMUP="1"),
            patch.object(api, "retrieve_candidates", side_effect=RuntimeError("unavailable")),
        ):
            api.warmup_retrieval()
        self.assertEqual(api.WARMUP_STATE["status"], "failed")

    def test_disabled_warmup_has_no_retrieval(self):
        with (
            patch.dict(os.environ, RECIPE_WARMUP="0"),
            patch.object(api, "retrieve_candidates") as query,
        ):
            api.warmup_retrieval()
        query.assert_not_called()
        self.assertEqual(api.WARMUP_STATE["status"], "disabled")

    def test_startup_waits_for_warmup(self):
        with patch.object(api, "warmup_retrieval") as warmup:
            with TestClient(application):
                warmup.assert_called_once()


class RelaxationNoticeTests(unittest.TestCase):
    def rows(self):
        recipes = [{"recipe_id": str(i)} for i in range(7)]
        prior = {
            r["recipe_id"]: {
                "status": "fail",
                "checks": [
                    dict(kind="ingredient", role="required", name="durian", decision="pass"),
                    dict(kind="dish_name", role="required", name="fruit salad", decision="fail"),
                ],
            }
            for r in recipes
        }
        levels = {
            "6": dict(
                source_level="relaxed",
                relaxation=[
                    dict(type="drop_ingredient", value="durian", sole_required_exception=True)
                ],
            )
        }
        return recipes, prior, levels, S(dish_name_target="fruit salad", dish_type_target="salad")

    def test_notice_uses_checked_strict_recipes_not_library_counts(self):
        notes = ingredient_relaxation_notes(*self.rows())
        self.assertEqual(notes[0]["strict_checked_count"], 6)
        self.assertEqual(notes[0]["dish_rejected_count"], 6)
        self.assertIn("They did not match fruit salad", notes[0]["message"])
        self.assertNotIn("library", notes[0]["message"])

    def test_unknown_identity_is_never_described_as_rejected(self):
        args = self.rows()
        args[1]["0"]["checks"][1]["decision"] = "unknown"
        note = ingredient_relaxation_notes(*args)[0]
        self.assertEqual(note["dish_rejected_count"], 5)
        self.assertNotIn("They did not match", note["message"])

    def test_prompt_is_partitioned_and_instruction_exception_explicit(self):
        for heading in (
            "GENERAL",
            "INGREDIENTS / CATEGORIES",
            "DISH IDENTITY",
            "CUISINE",
            "EVIDENCE FORMAT",
        ):
            self.assertIn(heading, CHECK_PROMPT)
        self.assertIn("continuous verbatim excerpt", CHECK_PROMPT)
        self.assertLess(len(CHECK_PROMPT.split()), 800)


import recipe_search.llm.content_generation as generation
from recipe_search.retrieval.relaxation_planner import plans_for
from tests.unit import test_content_generation as legacy


class RelaxationNoticeIntegrationTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp
    provider = legacy.ContentGenerationTests.provider

    def test_check_and_generation_share_grounded_note(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(
            query="fruit salad",
            dish_name_target="fruit salad",
            dish_type_target="salad",
            include_ingredients=["durian"],
            core_ingredients=["durian"],
        )
        docs = self.es.mget.return_value["docs"][:3]
        self.es.mget.return_value["docs"] = docs
        self.request["recipe_ids"] = ["1", "2", "3"]
        for i, doc in enumerate(docs):
            doc["_source"].update(
                name="Durian Cake" if i == 0 else "Fruit Salad",
                ingredients=["durian"] if i == 0 else ["banana"],
                keywords=["cake"] if i == 0 else ["salad"],
            )
        actions = plans_for(api.SearchRequest(**self.request["retrieval_snapshot"]))[0][0][
            "actions"
        ]
        self.request["retrieval_trace"] = {
            "generation_candidate_levels": {
                i: dict(source_level="relaxed", relaxation=actions) for i in ("2", "3")
            }
        }

        def change(out, payload, checking):
            if checking:
                for row in out["assessments"]:
                    for c in row["checks"]:
                        c.update(
                            status="not_matched",
                            evidence=["Durian Cake"],
                            reason="Recorded cake identity.",
                        )
            else:
                out["recommendations"] = []
                out["close_alternatives"] = [
                    dict(
                        recipe_id="2",
                        reason="Review the differences.",
                        flavor="Fruit",
                        best_for="Alternative",
                    )
                ]

        self.change = change
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider):
            checked = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
            self.assertEqual(checked.status_code, 200, checked.text)
            note = checked.json()["ingredient_relaxation_notes"][0]
            self.assertEqual(note["strict_checked_count"], 1)
            self.assertEqual(note["dish_rejected_count"], 1)
            generated = self.client.post(
                "/content/generate/deepseek-flash",
                json={"eligibility_id": checked.json()["eligibility_id"]},
            )
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertIn(note["message"], generated.json()["summary"])
        self.assertEqual(generated.json()["ingredient_relaxation_notes"][0], note)
        self.assertIn("No durian", checked.json()["assessments"][1]["deviations"][0]["reason"])
        self.assertNotIn(
            "not confirmed", checked.json()["assessments"][1]["deviations"][0]["reason"]
        )
