import copy
import json
import unittest
from unittest.mock import patch, MagicMock
import recipe_search.api.search as api
from recipe_search.retrieval.relaxation_planner import (
    plans_for,
    apply_actions,
    choose_relaxation,
    build_relaxation_aggs,
    classify_near_miss,
)
from recipe_search.matching.eligibility import constraints_for, local_checks, decision
from recipe_search.matching.constraint_logic import RequiredExpression as E
from tests.unit.test_rrf import hit
from tests.unit.test_search import candidates
import recipe_search.llm.content_generation as generation
from tests.unit import test_content_generation as legacy


def leaf(n):
    return E(op="ingredient", ingredient=n)


def both(*names):
    return E(op="AND", children=[leaf(n) for n in names])


class PlannerTests(unittest.TestCase):
    def request(self, **kw):
        return api.SearchRequest(relaxation_strategy="single", query="soup", **kw)

    def test_nested_and_flattened_before_relaxation(self):
        expr = E(op="AND", children=[both("beef", "onion"), leaf("pineapple")])
        self.assertEqual([c.ingredient for c in expr.children], ["beef", "onion", "pineapple"])
        plans, _ = plans_for(
            self.request(
                include_ingredients=["beef", "onion", "pineapple"], required_expression=expr
            )
        )
        self.assertEqual(
            {a["value"] for p in plans for a in p["actions"]}, {"beef", "onion", "pineapple"}
        )

    def test_zero_time_is_unknown_and_missing_bucket(self):
        r = self.request(
            numeric_filters=[
                dict(field="total_time", operator="lt", value=15, basis="not_applicable")
            ]
        )
        constraints, expr = constraints_for(r, None)
        self.assertEqual(
            decision("1", local_checks(dict(total_time_minutes=0), constraints), expr)["status"],
            "unknown",
        )
        self.assertIn('"gt": 0', json.dumps(api.build_filters(r)))
        stats, _, _ = build_relaxation_aggs(r, api.build_filters)
        self.assertIn('"lte": 0', json.dumps(stats["aggs"]["missing_numeric"]))

    def test_sole_required_exception_not_when_another_positive_filter_exists(self):
        r = self.request(
            include_ingredients=["durian"],
            required_expression=leaf("durian"),
            max_total_time_minutes=30,
        )
        self.assertFalse(
            any(a["type"] == "drop_ingredient" for p in plans_for(r)[0] for a in p["actions"])
        )

    def test_relaxed_source_does_not_prove_absence_for_missing_or_compound_data(self):
        from recipe_search.retrieval.relaxation_planner import assess_candidate

        r = self.request(include_ingredients=["pineapple"], required_expression=leaf("pineapple"))
        constraints, expr = constraints_for(r, None)
        meta = dict(source_level="relaxed", relaxation=plans_for(r)[0][0]["actions"])
        for recipe in [
            dict(ingredients=[]),
            dict(ingredients=[], extract_ingredients=["apple"]),
            dict(ingredients=["fruit mix"]),
        ]:
            self.assertEqual(
                assess_candidate("x", local_checks(recipe, constraints), meta, expr)["status"],
                "unknown",
            )
        recipe = dict(ingredients=["pineapple"])
        self.assertEqual(
            assess_candidate("x", local_checks(recipe, constraints), meta, expr)["status"], "pass"
        )

    def test_borderline_dish_only_allowed_for_completed_relaxed_identity_check(self):
        from recipe_search.retrieval.relaxation_planner import assess_candidate

        r = self.request(
            include_ingredients=["durian"],
            required_expression=leaf("durian"),
            dish_name_target="fruit salad",
        )
        constraints, expr = constraints_for(r, None)
        meta = dict(source_level="relaxed", relaxation=plans_for(r)[0][0]["actions"])
        recipe = dict(
            name="Banana Split Dessert or Salad",
            ingredients=["banana"],
            keywords=[],
            recipecategory=["dessert"],
        )
        pending = local_checks(recipe, constraints)
        self.assertEqual(assess_candidate("pending", pending, meta, expr)["status"], "unknown")

        def evaluated(dish_state="unknown", metadata=meta, extra=None):
            checks = local_checks(recipe, constraints)
            dish = next(c for c in checks if c["kind"] == "dish_name")
            dish.update(
                decision=dish_state,
                status={"unknown": "unknown", "pass": "matched", "fail": "not_matched"}[dish_state],
                source="model",
                semantic_required=False,
                evidence=[recipe["name"]],
            )
            if extra:
                checks.append(extra)
            return assess_candidate("x", checks, metadata, expr)

        borderline = evaluated()
        self.assertEqual(borderline["status"], "near_miss")
        self.assertEqual(len(borderline["deviations"]), 2)
        self.assertTrue(borderline["deviations"][1]["uncertain"])
        self.assertEqual(
            next(c for c in borderline["checks"] if c["kind"] == "dish_name")["decision"], "unknown"
        )
        self.assertEqual(evaluated("pass")["status"], "near_miss")
        self.assertEqual(len(evaluated("pass")["deviations"]), 1)
        self.assertEqual(evaluated("fail")["status"], "fail")
        self.assertEqual(evaluated(metadata={"source_level": "strict"})["status"], "unknown")
        extra = dict(
            constraint_id="hard-99",
            kind="numeric",
            name="total_time",
            role="required",
            decision="unknown",
            status="unknown",
            source="local",
            semantic_required=False,
            evidence=[],
            reason="Missing time",
        )
        self.assertEqual(evaluated(extra=extra)["status"], "unknown")
        extra.update(
            kind="ingredient", name="onion", role="excluded", decision="fail", status="matched"
        )
        self.assertEqual(evaluated(extra=extra)["status"], "fail")

    def test_core_and_or_protection(self):
        r = self.request(
            include_ingredients=["beef", "onion", "pineapple"],
            required_expression=both("beef", "onion", "pineapple"),
            dish_name_target="pineapple beef stir fry",
        )
        plans, protected = plans_for(r)
        self.assertEqual(
            {a["value"] for p in plans for a in p["actions"] if a["type"] == "drop_ingredient"},
            {"onion"},
        )
        self.assertEqual({c["name"] for c in protected if c["protected"]}, {"beef", "pineapple"})
        for expr, names in [
            (E(op="OR", children=[leaf("beef"), leaf("chicken")]), ["beef", "chicken"])
        ]:
            self.assertEqual(
                plans_for(self.request(include_ingredients=names, required_expression=expr))[0], []
            )

    def test_sole_specific_core_exception_removes_leaf_not_other_filters(self):
        r = self.request(
            include_ingredients=["durian"],
            core_ingredients=["durian"],
            required_expression=leaf("durian"),
            exclude_ingredients=["onion"],
            dish_name_target="fruit salad",
        )
        plans, protected = plans_for(r)
        plan = next(p for p in plans if p["actions"][0].get("sole_required_exception"))
        self.assertEqual(len(plan["actions"]), 1)
        self.assertTrue(protected[0]["sole_core_exception"])
        relaxed = apply_actions(r, plan["actions"])
        self.assertEqual(relaxed.include_ingredients, [])
        self.assertIsNone(relaxed.required_expression)
        self.assertEqual(relaxed.exclude_ingredients, ["onion"])
        self.assertEqual(relaxed.dish_name_target, "fruit salad")
        self.assertNotIn("durian", json.dumps(api.build_filters(relaxed)))
        self.assertEqual(r.required_expression.ingredient, "durian")
        category = self.request(
            category_required=["vegetable"], required_expression=leaf("vegetable")
        )
        self.assertFalse(plans_for(category)[0])

    def test_waived_leaf_skips_semantics_but_other_checks_and_strict_are_unchanged(self):
        from recipe_search.retrieval.relaxation_planner import assess_candidate

        r = self.request(
            include_ingredients=["durian"],
            core_ingredients=["durian"],
            required_expression=leaf("durian"),
            exclude_ingredients=["onion"],
            dish_name_target="fruit salad",
        )
        actions = plans_for(r)[0][0]["actions"]
        meta = dict(source_level="relaxed", relaxation=actions)
        constraints, expr = constraints_for(r, None)
        recipe = dict(
            name="Fresh Fruit Salad", ingredients=["apple"], keywords=[], recipecategory=[]
        )
        checks = local_checks(recipe, constraints)
        result = assess_candidate("new", checks, meta, expr)
        self.assertEqual(result["status"], "near_miss")
        self.assertFalse(checks[0]["semantic_required"])
        self.assertFalse(checks[0].get("waived"))
        self.assertEqual(checks[0]["status"], "not_matched")
        self.assertIsNotNone(result["required_expression"])
        self.assertFalse(result["waived_conditions"])
        strict = assess_candidate(
            "old", local_checks(recipe, constraints), dict(source_level="strict"), expr
        )
        self.assertEqual(strict["status"], "unknown")
        self.assertFalse(strict["waived_conditions"])
        excluded = {**recipe, "ingredients": ["apple", "onion"]}
        self.assertEqual(
            assess_candidate("bad", local_checks(excluded, constraints), meta, expr)["status"],
            "fail",
        )
        wrong = {**recipe, "name": "Durian Ice Cream"}
        self.assertEqual(
            assess_candidate("wrong", local_checks(wrong, constraints), meta, expr)["status"],
            "unknown",
        )

    def test_mixed_groups_only_top_level_specific_leaf_removable(self):
        expr = E(
            op="AND",
            children=[E(op="OR", children=[leaf("beef"), leaf("vegetable")]), leaf("rice")],
        )
        r = self.request(
            include_ingredients=["beef", "rice"],
            category_required=["vegetable"],
            required_expression=expr,
        )
        plans, _ = plans_for(r)
        self.assertEqual([a["value"] for p in plans for a in p["actions"]], ["rice"])
        self.assertEqual(apply_actions(r, plans[0]["actions"]).required_expression.op, "OR")

    def test_two_drop_actions_remove_both_original_and_leaves(self):
        r = self.request(
            include_ingredients=["beef", "onion"], required_expression=both("beef", "onion")
        )
        plans, _ = plans_for(r)
        pair = next(p for p in plans if len(p["actions"]) == 2)
        relaxed = apply_actions(r, pair["actions"])
        self.assertIsNone(relaxed.required_expression)
        self.assertEqual(relaxed.include_ingredients, [])
        self.assertEqual(r.include_ingredients, ["beef", "onion"])

    def test_precision_lower_bounds_eq_and_retained_filters(self):
        r = self.request(
            include_ingredients=["beef"],
            exclude_ingredients=["onion"],
            labels=["vegan"],
            max_total_time_minutes=15,
            numeric_filters=[dict(field="protein", operator="gte", value=30, basis="per_serving")],
        )
        plans, _ = plans_for(r)
        a = next(
            a
            for p in plans
            for a in p["actions"]
            if a.get("field") == "total_time" and a["level"] == 3
        )
        self.assertEqual(a["to"][0]["value"], 22.5)
        b = next(
            a
            for p in plans
            for a in p["actions"]
            if a.get("field") == "protein" and a["level"] == 1
        )
        self.assertEqual(b["to"][0]["value"], 25)
        relaxed = apply_actions(r, [a, b])
        self.assertEqual(relaxed.exclude_ingredients, ["onion"])
        self.assertEqual(relaxed.labels, ["vegan"])
        self.assertEqual(relaxed.include_ingredients, ["beef"])
        eq = self.request(
            numeric_filters=[dict(field="calories", operator="eq", value=300, basis="per_serving")]
        )
        self.assertFalse(plans_for(eq)[0])

    def test_named_filter_buckets_and_deterministic_selection(self):
        r = self.request(
            include_ingredients=["beef", "onion"],
            required_expression=both("beef", "onion"),
            core_ingredients=["beef"],
            max_total_time_minutes=15,
        )
        body, plans, _ = build_relaxation_aggs(r, api.build_filters)
        counts = {p["plan_id"]: 0 for p in plans}
        counts["strict"] = 2
        for p in plans:
            if len(p["actions"]) == 1:
                a = p["actions"][0]
                counts[p["plan_id"]] = (
                    2 if a["level"] == 1 else 7 if a["type"] == "drop_ingredient" else 12
                )
        selected = choose_relaxation(plans, counts, 10)
        self.assertEqual(selected["actions"][0]["level"], 3)
        text = json.dumps(body)
        self.assertNotIn("15.01", text)
        self.assertIn("22.5", text)
        self.assertEqual(
            len(body["aggs"]["relaxation_plans"]["filters"]["filters"]), len(plans) + 1
        )
        self.assertTrue(all(len(p["actions"]) <= 2 for p in plans))

    def test_threshold_alias_conflicts(self):
        self.assertEqual(self.request(bm25_fallback_threshold=5).strict_candidate_threshold, 5)
        with self.assertRaises(ValueError):
            self.request(bm25_fallback_threshold=5, strict_candidate_threshold=10)

    def test_near_miss_requires_all_other_conditions_and_explicit_failure(self):
        r = self.request(max_total_time_minutes=15, exclude_ingredients=["onion"])
        constraints, expr = constraints_for(r, None)
        recipe = dict(
            name="Soup", ingredients=["beef"], keywords=[], recipecategory=[], total_time_minutes=20
        )
        plans, _ = plans_for(r)
        action = next(a for p in plans for a in p["actions"] if a["level"] == 3)
        meta = dict(source_level="relaxed", relaxation=[action])

        def classify(rec):
            return classify_near_miss(
                decision("1", local_checks(rec, constraints), expr), meta, expr
            )

        self.assertEqual(classify(recipe)["status"], "near_miss")
        self.assertEqual(classify(recipe)["deviations"][0]["difference"], 5)
        self.assertEqual(classify({**recipe, "ingredients": ["onion"]})["status"], "fail")
        self.assertEqual(classify({**recipe, "ingredients": []})["status"], "unknown")
        self.assertEqual(classify({**recipe, "total_time_minutes": None})["status"], "unknown")


class RetrievalTests(unittest.TestCase):
    def es(self):
        client = MagicMock()
        client.options.return_value = client

        def search(**body):
            buckets = body["aggs"]["relaxation_plans"]["filters"]["filters"]
            return dict(
                aggregations={
                    "relaxation_plans": {
                        "buckets": {k: dict(doc_count=1 if k == "strict" else 20) for k in buckets}
                    }
                }
            )

        client.search.side_effect = search
        return client

    def test_both_branches_relax_and_keep_strict_first(self):
        calls = []
        client = self.es()

        def retrieve(r, f, b):
            calls.append((r, f, b))
            return (
                candidates([hit("strict")])
                if r.max_total_time_minutes
                else candidates([hit("strict"), hit("relaxed")])
            )

        r = api.SearchRequest(
            relaxation_strategy="single",
            query="soup",
            include_ingredients=["durian"],
            exclude_ingredients=["onion"],
            max_total_time_minutes=15,
        )
        with (
            patch.object(api, "get_client", return_value=client),
            patch.object(api, "retrieve_candidates", side_effect=retrieve),
        ):
            d = api.search(r)
        self.assertEqual(len(calls), 4)
        self.assertEqual(d["relaxation"]["status"], "complete")
        self.assertEqual([x["recipe_id"] for x in d["results"]], ["strict", "relaxed"])
        self.assertTrue(
            all(
                x.exclude_ingredients == ["onion"] and x.include_ingredients == ["durian"]
                for x, _, _ in calls
            )
        )
        self.assertEqual(d["generation_candidate_levels"]["strict"]["source_level"], "strict")
        self.assertEqual(d["generation_candidate_levels"]["relaxed"]["source_level"], "relaxed")
        self.assertEqual(d["original_conditions"]["max_total_time_minutes"], 15)
        for branch in ("bm25", "vector"):
            before = d["branch_results"][branch]["strict_baseline"]
            self.assertEqual(before["candidate_count"], 1)
            self.assertEqual([r["recipe_id"] for r in before["results"]], ["strict"])
            self.assertEqual(
                [r["recipe_id"] for r in d["branch_results"][branch]["results"]],
                ["strict", "relaxed"],
            )

    def test_sole_core_durian_drops_from_both_filters_and_preserves_strict_sources(self):
        seen = []

        def retrieve(r, f, b):
            seen.append((r.include_ingredients, r.required_expression, f, b))
            return (
                candidates([hit("strict")])
                if r.include_ingredients
                else candidates([hit("strict"), hit("fruit")])
            )

        with (
            patch.object(api, "get_client", return_value=self.es()),
            patch.object(api, "retrieve_candidates", side_effect=retrieve),
        ):
            data = api.search(
                api.SearchRequest(
                    relaxation_strategy="single",
                    query="fruit salad",
                    dish_name_target="fruit salad",
                    include_ingredients=["durian"],
                    core_ingredients=["durian"],
                )
            )
        self.assertEqual(len(seen), 4)
        self.assertEqual(sum(not row[0] for row in seen), 2)
        for include, expr, filters, branch in seen:
            if not include:
                self.assertIsNone(expr)
                self.assertNotIn("durian", json.dumps(filters))
        self.assertEqual(data["generation_candidate_levels"]["strict"]["source_level"], "strict")
        self.assertEqual(
            next(
                r for r in data["branch_results"]["vector"]["results"] if r["recipe_id"] == "fruit"
            )["vector_source_level"],
            "relaxed",
        )
        self.assertTrue(
            data["generation_candidate_levels"]["fruit"]["relaxation"][0]["sole_required_exception"]
        )

    def test_stream_progress_exposes_completed_counts_before_fusion(self):
        events = []

        def retrieve(r, f, b):
            return (
                candidates([hit("strict")])
                if r.max_calories
                else candidates([hit("strict"), hit("one"), hit("two")])
            )

        with (
            patch.object(api, "get_client", return_value=self.es()),
            patch.object(api, "retrieve_candidates", side_effect=retrieve),
        ):
            data = api.search(
                api.SearchRequest(relaxation_strategy="single", query="soup", max_calories=300),
                on_progress=events.append,
            )
        for branch in ("bm25", "vector"):
            done = next(e for e in events if e["step"] == branch and e["status"] == "complete")
            self.assertEqual(done["candidate_count"], 1)
            self.assertIsInstance(done["elapsed_ms"], (int, float))
            relaxed = next(
                e for e in events if e["step"] == "relaxed_" + branch and e["status"] == "complete"
            )
            self.assertEqual(relaxed["candidate_count"], 3)
            self.assertEqual(relaxed["added"], 2)
        merged = next(i for i, e in enumerate(events) if e["step"] == "candidate_merge")
        fusion = next(
            i for i, e in enumerate(events) if e["step"] == "rrf" and e["status"] == "running"
        )
        self.assertLess(merged, fusion)
        self.assertEqual(events[merged]["candidate_count"], 3)
        self.assertEqual(
            next(e for e in events if e["step"] == "rrf" and e["status"] == "complete")[
                "candidate_count"
            ],
            data["candidate_counts"]["rrf"],
        )

    def test_statistics_failure_preserves_strict_no_blind_retry(self):
        client = self.es()
        client.search.side_effect = TimeoutError()
        with (
            patch.object(api, "get_client", return_value=client),
            patch.object(api, "retrieve_candidates", return_value=candidates([hit("1")])) as recall,
        ):
            d = api.search(
                api.SearchRequest(relaxation_strategy="single", query="soup", max_calories=300)
            )
        self.assertEqual(recall.call_count, 2)
        self.assertEqual(d["relaxation"]["status"], "statistics_failed")
        self.assertEqual(d["results"][0]["recipe_id"], "1")

    def test_relaxed_failure_preserves_strict_and_single_modes(self):
        for mode in ("bm25", "vector", "hybrid"):

            def retrieve(r, f, b):
                if r.max_calories is None:
                    raise TimeoutError()
                return candidates([hit("1")])

            with (
                patch.object(api, "get_client", return_value=self.es()),
                patch.object(api, "retrieve_candidates", side_effect=retrieve),
            ):
                d = api.search(
                    api.SearchRequest(
                        relaxation_strategy="single", query="soup", mode=mode, max_calories=300
                    )
                )
            self.assertEqual(d["relaxation"]["status"], "failed")
            self.assertEqual(d["generation_candidate_ids"], ["1"])

    def test_inflight_embedding_shared_with_shallow_relaxed_request(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        started = threading.Event()
        release = threading.Event()
        r = api.SearchRequest(relaxation_strategy="single", query="soup", mode="vector")
        object.__setattr__(r, "_relax_embedding_state", {"lock": threading.Lock(), "vector": None})
        relaxed = r.model_copy(update={"vector_candidates": 10})

        def encode(*args):
            started.set()
            release.wait(2)
            return [1.0, 0.0]

        client = self.es()
        client.search.side_effect = None
        client.search.return_value = {"hits": {"hits": [hit("1")]}, "took": 1}
        with (
            patch.object(api, "get_client", return_value=client),
            patch.object(api, "get_model", return_value=object()),
            patch.object(api, "encode_query", side_effect=encode) as model,
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(api.retrieve_candidates, r, None, "vector")
                self.assertTrue(started.wait(1))
                second = pool.submit(api.retrieve_candidates, relaxed, None, "vector")
                release.set()
                first.result()
                second.result()
            self.assertEqual(model.call_count, 1)

    def test_embedding_is_reused_for_relaxed_vector(self):
        client = self.es()

        def search(**body):
            if "aggs" in body:
                buckets = body["aggs"]["relaxation_plans"]["filters"]["filters"]
                return {
                    "aggregations": {
                        "relaxation_plans": {
                            "buckets": {
                                k: {"doc_count": 1 if k == "strict" else 20} for k in buckets
                            }
                        }
                    }
                }
            self.assertEqual(body["knn"]["query_vector"], [1.0, 0.0])
            relaxed = "360.0" in json.dumps(body["knn"]["filter"])
            return {
                "hits": {"hits": [hit("strict"), hit("relaxed")] if relaxed else [hit("strict")]},
                "took": 1,
            }

        client.search.side_effect = search
        with (
            patch.object(api, "get_client", return_value=client),
            patch.object(api, "get_model", return_value=object()),
            patch.object(api, "encode_query", return_value=[1.0, 0.0]) as encode,
        ):
            d = api.search(
                api.SearchRequest(
                    relaxation_strategy="single", query="soup", mode="vector", max_calories=300
                )
            )
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(d["relaxation"]["status"], "complete")
        self.assertEqual(d["generation_candidate_ids"], ["strict", "relaxed"])

    def test_sufficient_strict_does_not_retry(self):
        with (
            patch.object(api, "get_client", return_value=self.es()),
            patch.object(
                api,
                "retrieve_candidates",
                return_value=candidates([hit(str(i)) for i in range(12)]),
            ) as recall,
        ):
            d = api.search(
                api.SearchRequest(relaxation_strategy="single", query="soup", max_calories=300)
            )
        self.assertEqual(recall.call_count, 2)
        self.assertEqual(d["relaxation"]["status"], "strict_sufficient")


class NearMissGenerationTests(unittest.TestCase):
    def setUp(self):
        legacy.ContentGenerationTests.setUp(self)
        self.request["retrieval_snapshot"]["relaxation_strategy"] = "single"

    provider = legacy.ContentGenerationTests.provider

    def test_sole_durian_waiver_completes_check_and_summary_without_claiming_presence(self):
        self.request["query"] = "fruit Salad with durian"
        self.request["intent_snapshot"]["raw_query"] = self.request["query"]
        extraction = self.request["intent_snapshot"]["parsed"]["extraction"]
        extraction.update(
            ingredients=[
                dict(
                    name="durian",
                    entity_type="specific",
                    role="required",
                    evidence="durian",
                    core=True,
                )
            ],
            dish_name="fruit salad",
            dish_type="salad",
            target_evidence=dict(
                dish_name="fruit Salad", dish_type="Salad", meal_type=None, cuisine=None
            ),
        )
        self.request["retrieval_snapshot"].update(
            query="fruit salad",
            include_ingredients=["durian"],
            core_ingredients=["durian"],
            dish_name_target="fruit salad",
            dish_type_target="salad",
        )
        actions = plans_for(api.SearchRequest(**self.request["retrieval_snapshot"]))[0][0][
            "actions"
        ]
        self.request["retrieval_trace"] = {
            "generation_candidate_levels": {
                i: dict(source_level="relaxed", relaxation=actions)
                for i in self.request["recipe_ids"]
            }
        }
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"].update(
                name="Fresh Fruit Salad", ingredients=["apple", "banana"], keywords=["salad"]
            )
        with patch.object(generation.urllib.request, "urlopen") as call:
            response = self.client.post(
                "/content/eligibility/deepseek-flash", json={**self.request, "local_only": True}
            )
        self.assertEqual(response.status_code, 200, response.text)
        call.assert_not_called()
        check = response.json()
        self.assertFalse(check["auto_completed"])
        self.assertEqual(check["constraint_counts"]["pass"], 0)
        self.assertGreater(check["constraint_counts"]["near_miss"], 0)
        with patch.object(generation.urllib.request, "urlopen") as call:
            response = self.client.post(
                "/content/eligibility/deepseek-flash", json={**self.request, "local_only": False}
            )
        self.assertEqual(response.status_code, 200, response.text)
        call.assert_not_called()
        self.assertTrue(response.json()["eligibility_id"])
        self.assertTrue(response.json()["near_miss_recipe_ids"])
        self.assertFalse(response.json()["qualified_recipe_ids"])
        pool = response.json()

        def change(out, p, checking):
            if not checking:
                out["recommendations"] = []
                out["close_alternatives"] = [
                    dict(
                        recipe_id=p["recipes"][0]["recipe_id"],
                        reason="Fruit salad without recorded durian.",
                        flavor="Fruit",
                        best_for="Salad",
                    )
                ]

        self.change = change
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider):
            generated = self.client.post(
                "/content/generate/deepseek-flash", json={"eligibility_id": pool["eligibility_id"]}
            )
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertIn("without durian", generated.json()["summary"])
        self.assertIn("groups below", generated.json()["summary"])
        self.assertFalse(generated.json()["recommendations"])

    def test_super_fruit_identity_evidence_survives_generation_recheck(self):
        quote = "Can be used as a breakfast fruit, a fruit salad, or a topping for plain cake, cookies, or ice cream."
        self.request["recipe_ids"] = ["1"]
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(
            include_ingredients=["cherries", "banana", "pineapple"],
            required_expression=both("cherries", "banana", "pineapple").model_dump(),
            exclude_ingredients=["eggs"],
            max_total_time_minutes=5,
            dish_name_target="fruit salad",
            dish_type_target="salad",
        )
        doc = self.es.mget.return_value["docs"][0]
        self.es.mget.return_value["docs"] = [doc]
        doc["_source"].update(
            name="Super Fruit",
            ingredients=["pineapple chunks", "maraschino cherries", "bananas"],
            keywords=[],
            recipecategory=[],
            instructions=[quote, "Unrelated source step."],
            total_time_minutes=5,
        )

        def change(out, p, checking):
            if not checking:
                self.assertEqual(p["recipes"][0]["identity_instruction_evidence"], [quote])
                self.assertNotIn("instructions", p["recipes"][0])
                self.assertEqual(len(p["recipes"][0]["previous_checks"]), 2)
            for assessment in out["assessments"]:
                for check in assessment["checks"]:
                    check.update(
                        status="matched",
                        evidence=[quote],
                        reason="Recorded instructions identify it as fruit salad.",
                    )

        self.change = change
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider):
            check = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
            self.assertEqual(check.status_code, 200, check.text)
            self.assertEqual(check.json()["constraint_counts"]["pass"], 1)
            generated = self.client.post(
                "/content/generate/deepseek-flash",
                json={"eligibility_id": check.json()["eligibility_id"], "recheck": True},
            )
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual([r["recipe_id"] for r in generated.json()["recommendations"]], ["1"])
        self.assertEqual(generated.json()["recheck_stats"]["overturned_count"], 0)

    def test_borderline_identity_check_and_summary_keep_one_deviation_first(self):
        self.request["recipe_ids"] = ["1", "2", "3"]
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(
            include_ingredients=["durian"], dish_name_target="fruit salad"
        )
        docs = self.es.mget.return_value["docs"][:3]
        self.es.mget.return_value["docs"] = docs
        for doc, name in zip(
            docs, ["Banana Split Dessert or Salad", "Fresh Fruit Salad", "Durian Cake"]
        ):
            doc["_source"].update(
                name=name,
                ingredients=["banana"],
                keywords=[],
                recipecategory=[],
                instructions=["Combine the recorded fruit."],
            )
        actions = plans_for(api.SearchRequest(**self.request["retrieval_snapshot"]))[0][0][
            "actions"
        ]
        self.request["retrieval_trace"] = {
            "generation_candidate_levels": {
                i: dict(source_level="relaxed", relaxation=actions)
                for i in self.request["recipe_ids"]
            }
        }

        def change(out, p, checking):
            if checking:
                for recipe, assessment in zip(p["recipes"], out["assessments"]):
                    self.assertIn("instructions", recipe)
                    for c in assessment["checks"]:
                        c.update(
                            status="unknown" if recipe["recipe_id"] == "1" else "not_matched",
                            evidence=[recipe["name"]],
                            reason="Borderline dessert salad."
                            if recipe["recipe_id"] == "1"
                            else "Clearly a cake.",
                        )
            else:
                self.assertEqual(p["candidate_groups"]["near_miss"], ["2", "1"])
                out["recommendations"] = []
                out["close_alternatives"] = [
                    dict(
                        recipe_id=i,
                        reason="Review the recorded differences.",
                        flavor="Fruit",
                        best_for="Alternative",
                    )
                    for i in ["1", "2"]
                ]

        self.change = change
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider):
            check = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
            self.assertEqual(check.status_code, 200, check.text)
            pool = check.json()
            self.assertEqual(pool["near_miss_recipe_ids"], ["2", "1"])
            self.assertFalse(pool["qualified_recipe_ids"])
            self.assertEqual(pool["constraint_counts"]["fail"], 1)
            output = self.client.post(
                "/content/generate/deepseek-flash",
                json={"eligibility_id": pool["eligibility_id"], "recheck": False},
            )
        self.assertEqual(output.status_code, 200, output.text)
        self.assertEqual([r["recipe_id"] for r in output.json()["close_alternatives"]], ["2", "1"])
        self.assertEqual(
            [len(r["deviations"]) for r in output.json()["close_alternatives"]], [1, 2]
        )

    def test_waiver_cannot_be_forged_for_and_or_category_or_unselected_action(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(
            include_ingredients=["beef", "rice"],
            core_ingredients=["beef", "rice"],
            required_expression=both("beef", "rice").model_dump(),
        )
        fake = dict(
            type="drop_ingredient", value="beef", level=2, ratio=1, sole_required_exception=True
        )
        self.request["retrieval_trace"] = {
            "generation_candidate_levels": {"1": dict(source_level="relaxed", relaxation=[fake])}
        }
        with patch.object(generation.urllib.request, "urlopen") as call:
            r = self.client.post(
                "/content/eligibility/deepseek-flash", json={**self.request, "local_only": True}
            )
        self.assertEqual(r.status_code, 422, r.text)
        call.assert_not_called()

    def test_numeric_near_only_pool_check_and_summary(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(max_total_time_minutes=15)
        action = plans_for(api.SearchRequest(**self.request["retrieval_snapshot"]))[0][0]["actions"]
        self.request["retrieval_trace"] = {
            "generation_candidate_levels": {
                i: dict(source_level="relaxed", relaxation=action)
                for i in self.request["recipe_ids"]
            }
        }
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"]["total_time_minutes"] = 17
        with patch.object(generation.urllib.request, "urlopen") as call:
            local = self.client.post(
                "/content/eligibility/deepseek-flash", json={**self.request, "local_only": True}
            )
            call.assert_not_called()
        self.assertEqual(local.status_code, 200, local.text)
        self.assertEqual(local.json()["constraint_counts"]["near_miss"], 23)
        with patch.object(generation.urllib.request, "urlopen") as call:
            d = self.client.post("/content/eligibility/deepseek-flash", json=self.request).json()
            call.assert_not_called()
        self.assertEqual(d["qualified_recipe_ids"], [])
        self.assertEqual(len(d["near_miss_recipe_ids"]), 5)
        self.assertTrue(d["eligibility_id"])

        def change(out, p, c):
            if not c:
                self.assertEqual(p["candidate_groups"]["pass"], [])
                self.assertEqual(len(p["candidate_groups"]["near_miss"]), 5)
                out["close_alternatives"] = [
                    dict(
                        recipe_id=p["recipes"][0]["recipe_id"],
                        reason="Takes 17 minutes rather than 15.",
                        flavor="Beef",
                        best_for="Close alternative",
                    )
                ]

        self.change = change
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider) as call:
            r = self.client.post(
                "/content/generate/deepseek-flash", json={"eligibility_id": d["eligibility_id"]}
            )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(r.json()["recommendations"], [])
        self.assertEqual(len(r.json()["close_alternatives"]), 1)
        self.assertEqual(r.json()["close_alternatives"][0]["deviations"][0]["difference"], 2)

    def test_sufficient_formal_pool_does_not_send_close_alternatives(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(max_total_time_minutes=15)
        action = plans_for(api.SearchRequest(**self.request["retrieval_snapshot"]))[0][0]["actions"]
        self.request["retrieval_trace"] = {
            "generation_candidate_levels": {
                str(i): dict(source_level="relaxed", relaxation=action) for i in range(21, 24)
            }
        }
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"]["total_time_minutes"] = 14 if int(doc["_id"]) <= 20 else 17
        with patch.object(generation.urllib.request, "urlopen") as call:
            r = self.client.post(
                "/content/eligibility/deepseek-flash", json={**self.request, "local_only": True}
            )
        self.assertEqual(r.status_code, 200, r.text)
        call.assert_not_called()
        self.assertTrue(r.json()["auto_completed"])
        self.assertEqual(r.json()["near_miss_recipe_ids"], [])
        self.assertEqual(len(r.json()["qualified_recipe_ids"]), 20)

    def test_summary_separates_formal_and_near_miss_groups(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.request["retrieval_snapshot"].update(max_total_time_minutes=15)
        action = plans_for(api.SearchRequest(**self.request["retrieval_snapshot"]))[0][0]["actions"]
        self.request["retrieval_trace"] = {
            "generation_candidate_levels": {
                i: dict(source_level="relaxed", relaxation=action)
                for i in self.request["recipe_ids"][1:]
            }
        }
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"]["total_time_minutes"] = 14 if doc["_id"] == "1" else 17
        with patch.object(generation.urllib.request, "urlopen") as call:
            d = self.client.post("/content/eligibility/deepseek-flash", json=self.request).json()
            call.assert_not_called()

        def change(out, p, c):
            if not c:
                self.assertEqual(p["candidate_groups"]["pass"], ["1"])
                self.assertEqual(len(p["candidate_groups"]["near_miss"]), 5)
                out["summary"] = "All six perfectly meet your requirements."
                out["close_alternatives"] = [
                    dict(
                        recipe_id="2",
                        reason="17 minutes rather than 15.",
                        flavor="Beef",
                        best_for="Extra time",
                    )
                ]

        self.change = change
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider):
            r = self.client.post(
                "/content/generate/deepseek-flash", json={"eligibility_id": d["eligibility_id"]}
            )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([a["recipe_id"] for a in r.json()["recommendations"]], ["1"])
        self.assertEqual([a["recipe_id"] for a in r.json()["close_alternatives"]], ["2"])
        self.assertIn("1 confirmed recipe", r.json()["summary"])
        self.assertNotIn("All six", r.json()["summary"])

    def test_source_images_returned_but_not_sent_to_model(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        self.es.mget.return_value["docs"][0]["_source"]["image_urls"] = [
            "https://example.com/source.jpg"
        ]
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider):
            r = self.client.post("/content/generate/deepseek-flash", json=self.request)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            r.json()["recipes"][0]["display_image_url"], "https://example.com/source.jpg"
        )
        for record in self.inputs[0]["recipes"]:
            self.assertNotIn("display_image_url", record)
            self.assertNotIn("image_urls", record)
            self.assertNotIn("fallback_image_url", record)

    def test_summary_schema_requires_alternative_output_for_openai(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []

        def provider(call, **kw):
            body = json.loads(call.data)
            schema = body["text"]["format"]["schema"]
            self.assertIn("close_alternatives", schema["required"])
            self.assertFalse(schema["additionalProperties"])
            return self.provider(call, **kw)

        with patch.object(generation.urllib.request, "urlopen", side_effect=provider):
            r = self.client.post("/content/generate/gpt41-mini", json=self.request)
        self.assertEqual(r.status_code, 200, r.text)

    def test_semantic_batches_finish_strict_layer_before_relaxed_and_stop(self):
        for i in range(24, 64):
            self.es.mget.return_value["docs"].append(
                {
                    "_id": str(i),
                    "found": True,
                    "_source": copy.deepcopy(self.es.mget.return_value["docs"][0]["_source"]),
                }
            )
        self.request["recipe_ids"] = [str(i) for i in range(1, 64)]
        self.request["retrieval_snapshot"].update(max_total_time_minutes=15)
        action = plans_for(api.SearchRequest(**self.request["retrieval_snapshot"]))[0][0]["actions"]
        self.request["retrieval_trace"] = {
            "generation_candidate_levels": {
                i: dict(source_level="relaxed", relaxation=action)
                for i in self.request["recipe_ids"][1:]
            }
        }
        for doc in self.es.mget.return_value["docs"]:
            doc["_source"]["total_time_minutes"] = 14 if doc["_id"] == "1" else 17
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider) as call:
            r = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(call.call_count, 3)
        self.assertEqual(self.inputs[0]["expected_recipe_ids"], ["1"])
        self.assertEqual(
            {tuple(p["expected_recipe_ids"]) for p in self.inputs[1:]},
            {tuple(str(i) for i in range(2, 22)), tuple(str(i) for i in range(22, 42))},
        )
        self.assertEqual(
            d["constraint_counts"],
            {"pass": 1, "near_miss": 40, "fail": 0, "unknown": 0, "not_checked": 22},
        )
        self.assertEqual(d["eligibility_stats"]["stop_reason"], "near_miss_target_reached")
