import io
import json
import unittest
from unittest.mock import patch
from recipe_search.matching.ingredient_match import expand, ingredient_clause
from recipe_search.matching.ingredient_sources import values, evidence_sources
from recipe_search.matching.eligibility import local_checks, apply_semantic, decision
from recipe_search.api.search import SearchRequest, build_filters, bm25_query, SOURCE_EXCLUDES
from recipe_search.ranking.preference_ranking import rerank
from recipe_search.llm.content_generation import Assessment, CategoryCheck
import recipe_search.llm.content_generation as service
from tests.unit import test_content_generation as legacy


class ExtractedIngredientTests(unittest.TestCase):
    def recipe(self, **kw):
        return dict(
            name="Soup",
            ingredients=["beef"],
            extract_ingredients=["onion", "broccoli"],
            extract_ingredients_firm=["onion", "broccoli"],
            keywords=[],
            recipecategory=[],
            **kw,
        )

    def constraint(self, name, role="required", kind="ingredient"):
        return dict(constraint_id="hard-1", kind=kind, name=name, role=role)

    def test_clause_covers_both_and_filters_share_union(self):
        clause = ingredient_clause("onions")
        terms = clause["bool"]["should"]
        self.assertEqual(
            {next(iter(t["terms"])) for t in terms}, {"ingredients", "extract_ingredients_firm"}
        )
        self.assertIn("onion", expand("onions", "extract_ingredients"))
        r = SearchRequest(query="soup", include_ingredients=["beef"], exclude_ingredients=["onion"])
        filters = build_filters(r)
        self.assertEqual(filters["bool"]["must_not"], [ingredient_clause("onion", excluded=True)])
        self.assertEqual(filters["bool"]["filter"], [ingredient_clause("beef")])
        bm = bm25_query("soup", filters, r)["bool"]
        reward = next(
            c["constant_score"]
            for c in bm["should"]
            if c.get("constant_score", {}).get("_name") == "required_ingredient_0"
        )
        self.assertEqual(reward["filter"], ingredient_clause("beef"))
        self.assertIn("extract_ingredients_firm^2", bm["must"][0]["multi_match"]["fields"])

    def test_no_empty_terms_and_unknown_required_stays_fail_closed(self):
        c = ingredient_clause("nonexistentingredientxyz")
        self.assertEqual(c, {"match_none": {}})
        self.assertIn(
            c,
            build_filters(
                SearchRequest(query="soup", include_ingredients=["nonexistentingredientxyz"])
            )["bool"]["filter"],
        )

    def test_specific_required_and_excluded_use_extracted(self):
        r = self.recipe()
        for role, status in [("required", "pass"), ("excluded", "fail")]:
            checks = local_checks(r, [self.constraint("onion", role)])
            self.assertEqual(checks[0]["decision"], status)
            self.assertEqual(
                checks[0]["evidence_sources"],
                [dict(field="extract_ingredients", value="onion", usage="preparation")],
            )
            self.assertIn("instructions", checks[0]["reason"])
        self.assertEqual(r["ingredients"], ["beef"])

    def test_empty_original_uses_extract_and_missing_both_stays_unknown(self):
        r = self.recipe()
        r["ingredients"] = []
        self.assertEqual(local_checks(r, [self.constraint("onion")])[0]["decision"], "pass")
        r["extract_ingredients"] = []
        self.assertEqual(
            local_checks(r, [self.constraint("onion", "excluded")])[0]["decision"], "unknown"
        )

    def test_category_semantic_evidence_can_quote_extract(self):
        r = self.recipe()
        checks = local_checks(r, [self.constraint("vegetable", "excluded", "category")])
        a = Assessment(
            recipe_id="1",
            checks=[
                CategoryCheck(
                    constraint_id="hard-1",
                    status="matched",
                    evidence=["extract_ingredients: broccoli"],
                    reason="Broccoli is a vegetable mentioned in instructions.",
                )
            ],
        )
        apply_semantic(a, r, checks, checks[:])
        self.assertEqual(checks[0]["decision"], "fail")
        self.assertEqual(
            checks[0]["evidence_sources"],
            [dict(field="extract_ingredients", value="broccoli", usage="preparation")],
        )
        bad = Assessment(
            recipe_id="1",
            checks=[
                CategoryCheck(
                    constraint_id="hard-1",
                    status="matched",
                    evidence=["invented carrot"],
                    reason="Invalid evidence.",
                )
            ],
        )
        warnings = apply_semantic(bad, r, checks, checks[:])
        self.assertEqual(checks[0]["decision"], "unknown")
        self.assertIn("downgraded", warnings[0])

    def test_duplicate_sources_preserved_without_double_preference_points(self):
        request = SearchRequest(
            query="soup",
            preference_available=["onion"],
            preference_prefer=["broccoli"],
            preference_avoid=["garlic"],
        )

        def row(original, extracted):
            return [
                dict(
                    rank=1,
                    rrf_score=0.2,
                    hit={
                        "_source": dict(
                            ingredients=original,
                            extract_ingredients=extracted,
                            extract_ingredients_firm=extracted,
                        )
                    },
                )
            ]

        expected = rerank(row(["onion", "broccoli", "garlic"], []), request)[0]
        extracted = rerank(row([], ["onion", "broccoli", "garlic"]), request)[0]
        duplicate = rerank(
            row(["onion", "broccoli", "garlic"], ["onion", "broccoli", "garlic"]), request
        )[0]
        self.assertEqual(expected["preference_score"], extracted["preference_score"])
        self.assertEqual(expected["preference_score"], duplicate["preference_score"])
        self.assertTrue(
            all(
                c["evidence_sources"][0]["field"] == "extract_ingredients"
                for e in extracted["preference_evidence"]
                for c in e["checks"]
            )
        )

    def test_matching_negation_and_and_logic(self):
        r = self.recipe()
        r["extract_ingredients"] = ["onion-free seasoning", "chicken broth"]
        r["extract_ingredients_firm"] = ["chicken broth"]
        self.assertEqual(
            local_checks(r, [self.constraint("onion", "excluded")])[0]["decision"], "pass"
        )
        self.assertEqual(local_checks(r, [self.constraint("chicken")])[0]["decision"], "pass")
        from recipe_search.matching.constraint_logic import RequiredExpression

        constraints = [
            self.constraint("beef"),
            dict(self.constraint("chicken"), constraint_id="hard-2"),
        ]
        checks = local_checks(r, constraints)
        expr = RequiredExpression.model_validate(
            dict(
                op="AND",
                children=[
                    dict(op="ingredient", ingredient="beef"),
                    dict(op="ingredient", ingredient="chicken"),
                ],
            )
        )
        self.assertEqual(decision("1", checks, expr)["status"], "pass")

    def test_source_helpers_preserve_fields_and_filter_non_strings(self):
        r = dict(ingredients=["onion", None], extract_ingredients=["onion", "broccoli", 5])
        self.assertEqual(values(r), ["onion", "broccoli"])
        self.assertEqual(len(evidence_sources(r, ["onion"])), 2)
        self.assertIn("extract_evidence", SOURCE_EXCLUDES)


class ExtractedIntegrationTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp

    def provider(self, call, **kwargs):
        body = json.loads(call.data)
        p = json.loads(body["messages"][-1]["content"] if "messages" in body else body["input"])
        self.inputs.append(p)
        checks = [
            dict(
                recipe_id=r["recipe_id"],
                checks=[
                    dict(
                        constraint_id=c["constraint_id"],
                        status="matched",
                        evidence=["broccoli"],
                        reason="Broccoli is mentioned in instructions.",
                    )
                    for c in r.get("pending_checks", [])
                ],
            )
            for r in p["recipes"]
        ]
        out = dict(assessments=checks)
        if "recommendation_limit" in p:
            out.update(
                summary="A soup with broccoli mentioned in its instructions.",
                recommendations=[
                    dict(
                        recipe_id=p["recipes"][0]["recipe_id"],
                        reason="Broccoli is mentioned in the instructions.",
                        flavor="Not specified",
                        best_for="Soup",
                    )
                ],
            )
        raw = {
            "status": "completed",
            "model": "mock",
            "usage": {"total_tokens": 10},
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": json.dumps(out)}]}
            ],
        }
        return io.BytesIO(json.dumps(raw).encode())

    def test_check_and_summary_receive_extracted_source_and_cache_invalidates(self):
        for d in self.es.mget.return_value["docs"]:
            d["_source"].update(
                ingredients=["beef"],
                extract_ingredients=["broccoli"],
                extract_ingredients_firm=["broccoli"],
                extract_evidence=[{"text": "never sent"}],
            )
        self.request["retrieval_snapshot"]["preference_prefer"] = ["broccoli"]
        with patch.object(service.urllib.request, "urlopen", side_effect=self.provider):
            r = self.client.post("/content/eligibility/gpt41-mini", json=self.request)
            self.assertEqual(r.status_code, 200, r.text)
            data = r.json()
            self.assertEqual(data["constraint_counts"]["pass"], 23)
            self.assertEqual(
                data["assessments"][0]["checks"][0]["evidence_sources"],
                [dict(field="extract_ingredients", value="broccoli", usage="preparation")],
            )
            self.assertIn("extract_ingredients", self.es.mget.call_args.kwargs["source_includes"])
            identifier = data["eligibility_id"]
            r = self.client.post(
                "/content/generate/gpt41-mini", json={"eligibility_id": identifier}
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["recipes"][0]["ingredients"], ["beef"])
            self.assertEqual(r.json()["recipes"][0]["extract_ingredients"], ["broccoli"])
            self.assertTrue(
                all(p["recipes"][0]["extract_ingredients"] == ["broccoli"] for p in self.inputs)
            )
            self.assertNotIn("extract_evidence", json.dumps(self.inputs))
            self.assertEqual(
                self.inputs[-1]["recipes"][0]["ingredient_preference_matches"][0][
                    "evidence_sources"
                ][0]["field"],
                "extract_ingredients",
            )
            self.es.mget.return_value["docs"][0]["_source"]["extract_ingredients"].append("onion")
            r = self.client.post("/content/eligibility/gpt41-mini", json=self.request)
            self.assertNotEqual(identifier, r.json()["eligibility_id"])
