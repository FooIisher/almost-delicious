import io
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import recipe_search.llm.gpt_intent_service as service
from recipe_search.api.app import app
from recipe_search.llm.extraction_schema import SCHEMA_VERSION, Extraction


def ingredient(name, role, entity_type="specific", evidence=None):
    return dict(name=name, role=role, entity_type=entity_type, evidence=evidence or name.strip())


def extraction(items, questions=None):
    return dict(
        intent="recipe_search",
        search_text="soup",
        dish_name=None,
        dish_type="soup",
        meal_type=None,
        cuisine=None,
        target_evidence=dict(dish_name=None, dish_type="soup", meal_type=None, cuisine=None),
        ingredients=items,
        bounds=[],
        dietary_restrictions=[],
        soft_preferences=[],
        corrections=[],
        clarification_questions=questions or [],
    )


class ConflictTests(unittest.TestCase):
    def invoke(self, query, parsed, model="gpt41-mini"):
        raw = dict(
            model=model if model == "deepseek-flash" else service.OPENAI_MODELS[model],
            usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )
        if model == "deepseek-flash":
            raw["choices"] = [dict(finish_reason="stop", message={"content": json.dumps(parsed)})]
        else:
            raw.update(
                status="completed",
                output=[
                    dict(
                        type="message", content=[dict(type="output_text", text=json.dumps(parsed))]
                    )
                ],
            )
        with (
            patch.dict("os.environ", OPENAI_API_KEY="test-key", DEEPSEEK_API_KEY="test-key"),
            patch.object(
                service.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(raw).encode())
            ) as call,
        ):
            result = TestClient(app).post("/intent/parse/" + model, json={"query": query})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(call.call_count, 1)
        body = json.loads(call.call_args.args[0].data)
        prompt = (
            body["messages"][0]["content"] if model == "deepseek-flash" else body["instructions"]
        )
        self.assertIn("vegetable soup without any vegetables", prompt)
        self.assertIn("vegetable broth is fine", prompt)
        self.assertEqual(result.json()["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result.json()["token_usage"]["total_tokens"], 120)
        return result.json()

    def test_category_conflict_all_four_models_preserves_evidence(self):
        items = [
            ingredient("vegetable", "required", "category", "vegetable"),
            ingredient("vegetables", "excluded", "category", "vegetables"),
        ]
        for model in ("gpt6", "gpt41-mini", "gpt41-nano", "deepseek-flash"):
            result = self.invoke(
                "I want vegetable soup without any vegetables", extraction(items), model
            )
            self.assertEqual(result["parsed"]["status"], "needs_clarification")
            self.assertIn("include vegetable", result["parsed"]["clarification_question"])
            self.assertEqual(
                result["parsed"]["extraction"]["ingredients"], [{**i, "core": False} for i in items]
            )
            self.assertFalse(result["filters_applied"])

    def test_case_whitespace_specific_name_and_question_dedup(self):
        items = [
            ingredient("  RED   onion", "required", evidence="onion"),
            ingredient("red onion ", "excluded", evidence="onion"),
        ]
        p = Extraction.model_validate(extraction(items))
        question = service.ingredient_conflict_questions(p)[0]
        self.assertIn("red onion", question)
        p.clarification_questions = [question]
        self.assertEqual(service.ingredient_conflict_questions(p), [question])
        result = self.invoke(
            "onion soup without onion",
            extraction(
                [ingredient("onion", "required"), ingredient("onion", "excluded")], [question]
            ),
        )
        self.assertEqual(result["parsed"]["status"], "needs_clarification")
        self.assertIn(question, result["parsed"]["extraction"]["clarification_questions"])

    def test_semantic_cross_category_model_question_preserved(self):
        question = "Do you mean beef broth without meat pieces, or a different soup?"
        result = self.invoke(
            "beef soup but no meat",
            extraction(
                [ingredient("beef", "required"), ingredient("meat", "excluded", "category")],
                [question],
            ),
        )
        self.assertEqual(result["parsed"]["status"], "needs_clarification")
        self.assertEqual(result["parsed"]["extraction"]["clarification_questions"], [question])

    def test_no_false_hard_conflicts(self):
        cases = [
            (
                "vegetable soup without onions",
                [ingredient("vegetable", "required", "category"), ingredient("onions", "excluded")],
            ),
            (
                "soup without vegetables",
                [ingredient("vegetable", "excluded", "category", "vegetables")],
            ),
            (
                "I have vegetables but do not use vegetables in soup",
                [
                    ingredient("vegetable", "available", "category", "vegetables"),
                    ingredient("vegetable", "excluded", "category", "vegetables"),
                ],
            ),
            (
                "vegetable soup but I dislike onions",
                [ingredient("vegetable", "required", "category"), ingredient("onions", "avoid")],
            ),
            (
                "I prefer vegetables but exclude vegetables in soup",
                [
                    ingredient("vegetable", "prefer", "category", "vegetables"),
                    ingredient("vegetable", "excluded", "category", "vegetables"),
                ],
            ),
        ]
        for query, items in cases:
            with self.subTest(query=query):
                self.assertEqual(self.invoke(query, extraction(items))["parsed"]["status"], "ready")

    def test_qualified_broth_preserved_without_global_exclusion(self):
        p = extraction([ingredient("vegetable", "required", "category")])
        p["dietary_restrictions"] = ["no vegetable pieces"]
        r = self.invoke("vegetable soup: vegetable broth is fine, but no vegetable pieces", p)
        self.assertEqual(r["parsed"]["status"], "ready")
        self.assertEqual(r["parsed"]["extraction"]["dietary_restrictions"], ["no vegetable pieces"])

    def test_groups_roles_and_time_roundtrip_four_models(self):
        for model in ("gpt41-mini", "gpt41-nano", "gpt6", "deepseek-flash"):
            p = extraction([ingredient("beef", "required"), ingredient("chicken", "required")])
            p["required_expression"] = dict(
                op="OR",
                ingredient=None,
                children=[
                    dict(op="ingredient", ingredient=n, children=[]) for n in ("beef", "chicken")
                ],
            )
            p["cuisine"] = "italian"
            p["cuisine_role"] = "prefer"
            p["target_evidence"]["cuisine"] = "Italian"
            p["bounds"] = [
                dict(
                    field="total_time",
                    operator="lte",
                    value=15,
                    unit="minutes",
                    basis="not_applicable",
                    evidence="15-minute",
                )
            ]
            result = self.invoke(
                "Find beef or chicken soup, 15-minute. I prefer Italian flavors.", p, model
            )
            parsed = result["parsed"]["extraction"]
            self.assertEqual(parsed["required_expression"]["op"], "OR")
            self.assertEqual(parsed["cuisine_role"], "prefer")
            self.assertEqual(parsed["bounds"][0]["operator"], "lte")

    def test_numeric_conflict_backend_requires_clarification(self):
        p = extraction([])
        p["bounds"] = [
            dict(
                field="total_time",
                operator=op,
                value=value,
                unit="minutes",
                basis="not_applicable",
                evidence=evidence,
            )
            for op, value, evidence in [("gte", 20, "20 minutes"), ("lt", 15, "15 minutes")]
        ]
        r = self.invoke("soup in at least 20 minutes but under 15 minutes", p)
        self.assertEqual(r["parsed"]["status"], "needs_clarification")
        self.assertIn("limits conflict", r["parsed"]["clarification_question"])

    def test_backend_does_not_infer_categories_or_strip_s(self):
        p = Extraction.model_validate(
            extraction([ingredient("beef", "required"), ingredient("meat", "excluded", "category")])
        )
        self.assertEqual(service.ingredient_conflict_questions(p), [])
        p = Extraction.model_validate(
            extraction([ingredient("peas", "required"), ingredient("pea", "excluded")])
        )
        self.assertEqual(service.ingredient_conflict_questions(p), [])
