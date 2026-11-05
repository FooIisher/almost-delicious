"""v2 regressions use deterministic ES/model doubles; never live paid calls."""

import copy
import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import recipe_search.api.search as api
import recipe_search.llm.content_generation as generation
from recipe_search.retrieval.relaxation_planner import (
    choose_relaxation_set,
    plans_for,
    apply_actions,
    assess_candidate,
    alternative_groups,
    group_targets_complete,
)
from recipe_search.retrieval.multi_relaxation import execute_relaxed, filter_matches
from recipe_search.matching.constraint_logic import RequiredExpression as E
from recipe_search.matching.eligibility import constraints_for, local_checks
from tests.unit.test_search import candidates
from tests.unit import test_content_generation as legacy


def leaf(name):
    return E(op="ingredient", ingredient=name)


def request(**kwargs):
    return api.SearchRequest(query="soup", **kwargs)


def hit(identifier, ingredients=None, minutes=14):
    return dict(
        _id=identifier,
        _score=1.0,
        _source=dict(
            recipeid=identifier,
            name="Soup " + identifier,
            ingredients=ingredients or ["beef", "onion", "pineapple"],
            total_time_minutes=minutes,
            keywords=["soup"],
            recipecategory=["soup"],
        ),
    )


def plans(r):
    variants, _ = plans_for(r)
    counts = {"strict": 0, **{p["plan_id"]: 50 for p in variants}}
    return choose_relaxation_set(variants, counts)


def client_for(r, fail=None, slow=False):
    client = MagicMock()
    client.options.return_value = client
    client.bodies = []

    def search(**body):
        if "aggs" in body:
            keys = body["aggs"]["relaxation_plans"]["filters"]["filters"]
            return {
                "aggregations": {
                    "relaxation_plans": {
                        "buckets": {k: {"doc_count": 0 if k == "strict" else 50} for k in keys}
                    }
                }
            }
        return {"hits": {"hits": []}, "took": 1}

    client.search.side_effect = search

    def msearch(searches, **kwargs):
        client.bodies.append(copy.deepcopy(searches))
        responses = []
        for index in range(1, len(searches), 2):
            body = searches[index]
            condition = body.get("knn", {}).get("filter") or body.get("query")
            fixtures = [
                hit("nobeef", ["onion", "pineapple"]),
                hit("noonion", ["beef", "pineapple"]),
                hit("nopineapple", ["beef", "onion"]),
                hit("long", minutes=17),
            ]
            # BM25 bool contains a base text must. Only evaluate its filter part.
            if "knn" not in body and "multi_match" in json.dumps(condition):
                condition = {
                    "bool": {
                        k: condition["bool"][k]
                        for k in ("filter", "must_not")
                        if k in condition["bool"]
                    }
                }
            rows = [h for h in fixtures if filter_matches(condition, h["_source"])][: body["size"]]
            responses.append(
                {"error": {"type": "simulated"}}
                if fail == index
                else {"hits": {"hits": rows}, "took": 2}
            )
        if slow and len(client.bodies) > 1:
            time.sleep(0.09)
        return {"responses": responses}

    client.msearch.side_effect = msearch
    return client


class MultiPlannerTests(unittest.TestCase):
    def test_fenner_example_distinct_directions_and_counts(self):
        r = request(
            include_ingredients=["beef", "onion", "pineapple"],
            required_expression=E(
                op="AND", children=[leaf(x) for x in ["beef", "onion", "pineapple"]]
            ),
            max_total_time_minutes=15,
        )
        variants, _ = plans_for(r)
        counts = {"strict": 0}
        for p in variants:
            a = p["actions"][0]
            counts[p["plan_id"]] = (
                100
                if len(p["actions"]) == 2
                else {"onion": 2, "beef": 124, "pineapple": 244}.get(
                    a.get("value"), 2 if a.get("level") == 1 else 11 if a.get("level") == 3 else 127
                )
            )
        selected = choose_relaxation_set(variants, counts)
        self.assertEqual(
            [p["actions"][0].get("value") or p["actions"][0]["field"] for p in selected],
            ["beef", "pineapple", "total_time"],
        )
        self.assertEqual(selected[-1]["actions"][0]["level"], 3)
        self.assertFalse(any(len(p["actions"]) > 1 for p in selected))

    def test_pairs_only_when_fewer_than_two_single_directions(self):
        r = request(
            numeric_filters=[
                dict(field=f, operator="lte", value=100, basis="per_serving")
                for f in ["calories", "protein"]
            ]
        )
        variants, _ = plans_for(r)
        counts = {
            "strict": 0,
            **{p["plan_id"]: 5 if len(p["actions"]) == 2 else 2 for p in variants},
        }
        selected = choose_relaxation_set(variants, counts)
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(selected[0]["actions"]), 2)
        self.assertFalse(
            choose_relaxation_set(variants, {"strict": 10, **{p["plan_id"]: 10 for p in variants}})
        )

    def test_core_category_or_and_manual_constraints_preserved(self):
        r = request(
            include_ingredients=["beef", "onion"],
            core_ingredients=["beef"],
            required_expression=E(op="AND", children=[leaf("beef"), leaf("onion")]),
            exclude_ingredients=["peanut"],
            labels=["soup"],
        )
        selected = plans(r)
        self.assertEqual([p["actions"][0]["value"] for p in selected], ["onion"])
        changed = apply_actions(r, selected[0]["actions"])
        self.assertEqual(changed.exclude_ingredients, ["peanut"])
        self.assertEqual(changed.labels, ["soup"])
        self.assertEqual(
            plans(request(category_required=["meat"], required_expression=leaf("meat"))), []
        )
        self.assertEqual(
            plans(
                request(
                    include_ingredients=["beef", "onion"],
                    required_expression=E(op="OR", children=[leaf("beef"), leaf("onion")]),
                )
            ),
            [],
        )


class MultiExecutionTests(unittest.TestCase):
    def setUp(self):
        self.r = request(
            include_ingredients=["beef", "onion", "pineapple"],
            required_expression=E(
                op="AND", children=[leaf(x) for x in ["beef", "onion", "pineapple"]]
            ),
        )
        object.__setattr__(
            self.r, "_relax_embedding_state", {"lock": threading.Lock(), "vector": [1.0, 0.0]}
        )
        self.plans = plans(self.r)

    def test_msearch_combined_knn_provenance_no_embedding(self):
        es = client_for(self.r)
        with (
            patch.object(api, "get_client", return_value=es),
            patch.object(api, "encode_query") as encode,
        ):
            result = execute_relaxed(
                self.r, self.plans, ["bm25", "vector"], set(), lambda *a, **kw: None
            )
        self.assertEqual(encode.call_count, 0)
        self.assertEqual(result["bm25"]["status"], "complete")
        self.assertEqual(result["vector"]["status"], "complete")
        self.assertEqual(
            len([b for b in es.bodies if any("knn" in x for x in b)]), 3
        )  # combined + two quota refills
        combined = next(
            x["knn"] for b in es.bodies for x in b if "knn" in x and x["knn"]["k"] == 15
        )
        self.assertEqual(len(combined["filter"]["bool"]["should"]), 3)
        self.assertEqual(combined["query_vector"], [1.0, 0.0])
        self.assertEqual(combined["num_candidates"], 100)
        self.assertEqual(
            {h["_id"] for h in result["bm25"]["hits"]}, {"nobeef", "noonion", "nopineapple", "long"}
        )
        long = next(h for h in result["vector"]["hits"] if h["_id"] == "long")
        self.assertEqual(len(long["source_plans"]), 3)

    def test_small_plan_direct_no_knn_and_no_false_similarity(self):
        p = self.plans[:1]
        p[0]["filter_match_count"] = 3
        es = client_for(self.r)
        with patch.object(api, "get_client", return_value=es):
            result = execute_relaxed(self.r, p, ["vector"], set(), lambda *a, **kw: None)
        self.assertEqual(result["vector"]["status"], "complete")
        self.assertNotIn("knn", json.dumps(es.bodies))
        self.assertIsNone(result["vector"]["hits"][0]["_score"])
        self.assertEqual(result["vector"]["plans"][0]["method"], "small_plan_direct")

    def test_partial_subquery_failure_retains_other_directions(self):
        es = client_for(self.r, fail=3)
        with patch.object(api, "get_client", return_value=es):
            result = execute_relaxed(self.r, self.plans, ["bm25"], set(), lambda *a, **kw: None)
        self.assertEqual(result["bm25"]["status"], "partial")
        self.assertTrue(result["bm25"]["hits"])
        self.assertEqual(result["bm25"]["plans"][1]["status"], "failed")

    def test_timeout_keeps_completed_combined_results(self):
        r = self.r.model_copy(update={"relaxation_timeout_seconds": 0.04})
        es = client_for(r, slow=True)
        with patch.object(api, "get_client", return_value=es):
            result = execute_relaxed(r, self.plans, ["vector"], set(), lambda *a, **kw: None)
        self.assertEqual(result["vector"]["status"], "partial")
        self.assertTrue(result["vector"]["hits"])
        frozen = copy.deepcopy(result)
        time.sleep(0.12)
        self.assertEqual(frozen, result)

    def test_api_default_multi_and_strict_baseline(self):
        es = client_for(self.r)

        def retrieve(r, f, name):
            if name == "vector":
                r._relax_embedding_state["vector"] = [1.0, 0.0]
            return candidates([hit("strict")])

        with (
            patch.object(api, "get_client", return_value=es),
            patch.object(api, "retrieve_candidates", side_effect=retrieve),
        ):
            data = api.search(self.r)
        self.assertEqual(len(data["relaxation"]["selected_plans"]), 3)
        self.assertEqual(data["generation_candidate_ids"][0], "strict")
        for branch in ["bm25", "vector"]:
            self.assertIn("strict_baseline", data["branch_results"][branch])
        self.assertTrue(data["generation_candidate_levels"]["nobeef"]["source_plans"])
        self.assertEqual(data["relaxation"]["status"], "complete")

    def test_no_relaxation_when_strict_sufficient(self):
        es = client_for(self.r)
        with (
            patch.object(api, "get_client", return_value=es),
            patch.object(
                api,
                "retrieve_candidates",
                return_value=candidates([hit(str(i)) for i in range(10)]),
            ),
        ):
            data = api.search(self.r)
        self.assertEqual(data["relaxation"]["selected_plans"], [])
        es.msearch.assert_not_called()


class MultiGroupsTests(unittest.TestCase):
    def test_groups_use_actual_deviations_and_keep_original_qualification(self):
        r = request(
            include_ingredients=["beef", "onion"],
            required_expression=E(op="AND", children=[leaf("beef"), leaf("onion")]),
        )
        p = plans(r)
        constraints, expr = constraints_for(r, None)
        prior = {}
        recipes = []
        levels = {}
        for index, ingredients in enumerate([["beef"], ["beef"], ["onion"], ["onion"]]):
            recipe = dict(recipe_id=str(index), ingredients=ingredients)
            recipes.append(recipe)
            a = next(
                x
                for x in p
                if x["actions"][0]["value"] == ("onion" if ingredients == ["beef"] else "beef")
            )
            levels[str(index)] = dict(
                source_level="relaxed", relaxation=a["actions"], source_plans=[a["plan_id"]]
            )
            prior[str(index)] = assess_candidate(
                str(index), local_checks(recipe, constraints), levels[str(index)], expr
            )
        groups = alternative_groups(recipes, prior)
        self.assertEqual({g["group_key"] for g in groups}, {"missing:beef", "missing:onion"})
        self.assertTrue(all(len(g["recipe_ids"]) == 2 for g in groups))
        self.assertTrue(all(a["status"] == "near_miss" for a in prior.values()))
        self.assertTrue(group_targets_complete(prior, levels))
        prior["3"].update(status="not_checked", checks=[dict(semantic_required=True)])
        self.assertFalse(group_targets_complete(prior, levels))


class MultiGenerationTests(unittest.TestCase):
    setUp = legacy.ContentGenerationTests.setUp
    provider = legacy.ContentGenerationTests.provider

    def test_check_groups_summary_roundtrip_and_original_requirements(self):
        self.request["intent_snapshot"]["parsed"]["extraction"]["ingredients"] = []
        r = request(
            include_ingredients=["beef", "onion"],
            required_expression=E(op="AND", children=[leaf("beef"), leaf("onion")]),
        )
        selected = plans(r)
        self.request["retrieval_snapshot"] = r.model_dump()
        self.request["recipe_ids"] = ["1", "2", "3", "4"]
        self.es.mget.return_value["docs"] = self.es.mget.return_value["docs"][:4]
        levels = {}
        for index, doc in enumerate(self.es.mget.return_value["docs"]):
            doc["_source"]["ingredients"] = ["beef"] if index < 2 else ["onion"]
            p = next(
                p
                for p in selected
                if p["actions"][0]["value"] == ("onion" if index < 2 else "beef")
            )
            levels[doc["_id"]] = dict(
                source_level="relaxed",
                relaxation=p["actions"],
                relaxation_plans=[p],
                source_plans=[p["plan_id"]],
            )
        self.request["retrieval_trace"] = {"generation_candidate_levels": levels}
        with patch.object(generation.urllib.request, "urlopen", side_effect=self.provider) as calls:
            checked = self.client.post("/content/eligibility/deepseek-flash", json=self.request)
            self.assertEqual(checked.status_code, 200, checked.text[:600])
            self.assertEqual(calls.call_count, 0)
            data = checked.json()
            self.assertEqual(data["constraint_counts"]["pass"], 0)
            self.assertEqual(len(data["alternative_groups"]), 2)

            def response(output, payload, checking):
                self.assertFalse(checking)
                self.assertEqual(len(payload["alternative_groups"]), 2)
                self.assertEqual(payload["required_expression"]["op"], "AND")
                output.update(
                    recommendations=[],
                    close_alternatives=[
                        dict(
                            recipe_id=i,
                            reason="A checked tradeoff.",
                            flavor="Recorded",
                            best_for="Alternative",
                        )
                        for g in payload["alternative_groups"]
                        for i in g["recipe_ids"]
                    ],
                    group_summaries=[
                        dict(
                            group_key=g["group_key"],
                            summary="Keeps one requested ingredient; the other is not recorded.",
                        )
                        for g in payload["alternative_groups"]
                    ],
                )

            self.change = response
            generated = self.client.post(
                "/content/generate/deepseek-flash", json={"eligibility_id": data["eligibility_id"]}
            )
        self.assertEqual(generated.status_code, 200, generated.text[:700])
        self.assertEqual(len(generated.json()["close_alternatives"]), 4)
        self.assertEqual(generated.json()["recommendations"], [])
        self.assertTrue(all(g["summary"] for g in generated.json()["alternative_groups"]))


if __name__ == "__main__":
    unittest.main()
