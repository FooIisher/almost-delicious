import json
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

import recipe_search_api as api
from retrieval_execution import execute_branches
from test_rrf import hit


def candidates(hits):
    return {"hits": hits, "timings": {}, "total": {"value": len(hits), "relation": "eq"}}


class FakeES:
    def __init__(self):
        self.calls = []
        self.options_calls = []

    def options(self, **kwargs):
        self.options_calls.append(kwargs)
        return self

    def search(self, **body):
        self.calls.append(body)
        hits = [hit("a"), hit("b")] if "query" in body else [hit("b"), hit("c")]
        return {"hits": {"hits": hits, "total": {"value": 20, "relation": "eq"}},
                "timed_out": False, "_shards": {"failed": 0}}


class SearchTests(unittest.TestCase):
    def test_mode_defaults_and_weighted_api(self):
        for mode in ("bm25", "vector", "hybrid"):
            request = api.SearchRequest(query="chicken", mode=mode)
            self.assertEqual(request.size, 20)
            self.assertEqual(request.rrf_k, 10)
            self.assertEqual(request.vector_num_candidates, 500)
        self.assertEqual(api.SearchRequest(query="x", vector_candidates=300).vector_num_candidates, 300)
        with patch.object(api, "retrieve_candidates", return_value=candidates([hit(1)])):
            response = api.search(api.SearchRequest(query="x", bm25_boost=2, vector_boost=3, rrf_k=1))
        self.assertEqual(response["results"][0]["rrf_score"], 2.5)
        self.assertEqual(response["rrf"]["bm25_boost"], 2)
        self.assertEqual(response["rrf"]["vector_boost"], 3)
        for boost in (0, -1, float("inf"), True):
            with self.assertRaises(ValidationError):
                api.SearchRequest(query="x", vector_boost=boost)

    def test_generation_pool_retains_rrf_top_100(self):
        with patch.object(api, 'retrieve_candidates', return_value=candidates([hit(str(i)) for i in range(150)])):
            response=api.search(api.SearchRequest(query='soup',size=2))
        self.assertEqual(len(response['results']),2)
        self.assertEqual(len(response['generation_candidate_ids']),100)
        self.assertEqual(response['candidate_counts']['rrf'],100)
        self.assertEqual(response['generation_candidate_ids'][:2],[row['recipe_id'] for row in response['results']])

    def test_identical_filters_and_independent_candidate_requests(self):
        client = FakeES()
        request = api.SearchRequest(query="chicken", include_ingredients=["chicken"],
                                    exclude_ingredients=["peanut"], labels=[" Soup ", "soup", "CHINESE"], max_total_time_minutes=30, max_calories=700)
        with patch.object(api, "get_client", return_value=client), \
             patch.object(api, "get_model", return_value=object()), \
             patch.object(api, "encode_query", return_value=[.1, .2]):
            response = api.search(request)
        self.assertEqual(response['effective_filters']['labels'], ['soup', 'chinese'])
        clauses = api.build_filters(request)['bool']['filter']
        label_clause = next(c['bool'] for c in clauses if 'bool' in c and any('term' in item for item in c['bool'].get('should',[])))
        self.assertEqual(label_clause['minimum_should_match'], 1)
        self.assertEqual(label_clause['should'], [
            {'term': {field: {'value': label, 'case_insensitive': True}}}
            for label in ['soup', 'chinese'] for field in ['recipecategory', 'keywords']])
        lexical = next(body for body in client.calls if "query" in body)
        vector = next(body for body in client.calls if "knn" in body)
        self.assertNotIn("knn", lexical)
        self.assertNotIn("query", vector)
        for key in ("filter", "must_not"):
            self.assertEqual(lexical["query"]["bool"][key], vector["knn"]["filter"]["bool"][key])
        self.assertIn("instructions",lexical["source"]["excludes"])
        self.assertIn("extract_evidence",vector["source"]["excludes"])
        self.assertNotIn("es_source",response["results"][0])
        self.assertEqual(lexical["size"], 500)
        self.assertEqual(vector["knn"]["k"], 500)
        self.assertEqual(vector["knn"]["num_candidates"], 500)
        self.assertEqual(response["results"][0]["recipe_id"], "b")
        self.assertEqual(response["candidate_counts"], {"bm25": 2, "vector": 2, "union": 3, "rrf": 3,"by_source_level":{"original":2,"relaxed":0}})
        self.assertEqual(response["match_result_size"]["scope"], "candidate_union")
        self.assertEqual(response["effective_filters"]["max_total_time_minutes"], 30)
        self.assertGreaterEqual(response["timings"]["vector_recall_ms"], response["timings"]["query_embedding_ms"])
        self.assertGreaterEqual(response["timings"]["search_total_ms"], response["timings"]["bm25_recall_ms"])

    def test_embedding_runs_concurrently_with_bm25(self):
        rendezvous = threading.Barrier(2)
        client = FakeES()
        original_search = client.search

        def es_search(**body):
            if "query" in body:
                rendezvous.wait(timeout=2)
            return original_search(**body)

        def embedding(*_):
            rendezvous.wait(timeout=2)
            return [.1]

        client.search = es_search
        with patch.object(api, "get_client", return_value=client), \
             patch.object(api, "get_model", return_value=object()), \
             patch.object(api, "encode_query", side_effect=embedding):
            response = api.search(api.SearchRequest(query="chicken"))
        self.assertEqual(response["effective_mode"], "hybrid")

    def test_serial_and_parallel_produce_same_ranking(self):
        def retrieve(request, filters, branch):
            return candidates([hit("a"), hit("b")] if branch == "bm25" else [hit("b"), hit("c")])
        with patch.object(api, "retrieve_candidates", side_effect=retrieve):
            serial = api.search(api.SearchRequest(query="chicken", execution="serial"))
            parallel = api.search(api.SearchRequest(query="chicken", execution="parallel"))
        self.assertEqual(serial["results"], parallel["results"])

    def test_single_failure_is_explicit_and_two_failures_raise(self):
        def retrieve(request, filters, branch):
            if branch == "vector":
                raise ConnectionError("not exposed")
            return candidates([hit("a")])
        with patch.object(api, "retrieve_candidates", side_effect=retrieve):
            response = api.search(api.SearchRequest(query="chicken"))
        self.assertEqual(response["effective_mode"], "bm25")
        self.assertEqual(response["branches"]["vector"]["status"], "failed")
        self.assertTrue(response["warnings"])
        self.assertEqual(response["results"][0]["vector_contribution"], 0)
        with patch.object(api, "retrieve_candidates", side_effect=ConnectionError):
            with self.assertRaisesRegex(RuntimeError, "No retrieval branch succeeded"):
                api.search(api.SearchRequest(query="chicken"))

    def test_empty_successful_branch_is_not_degraded(self):
        with patch.object(api,"get_client",side_effect=TimeoutError),patch.object(api, "retrieve_candidates", return_value=candidates([])):
            response = api.search(api.SearchRequest(query="chicken", max_calories=1))
        self.assertEqual(response["effective_mode"], "hybrid")
        self.assertTrue(any("Statistics unavailable" in w for w in response["warnings"]))
        self.assertEqual(response["results"], [])
        self.assertEqual(response["effective_filters"]["max_calories"], 1)

    def test_partial_es_response_is_rejected(self):
        client = FakeES()
        for partial in ({"timed_out": True}, {"_shards": {"failed": 1}}):
            client.search = lambda **body: partial
            with patch.object(api, "get_client", return_value=client):
                with self.assertRaises(RuntimeError):
                    api.retrieve_candidates(api.SearchRequest(query="chicken", mode="bm25"), None, "bm25")

    def test_single_modes_keep_original_scores_and_skip_fusion(self):
        with patch.object(api, "retrieve_candidates", return_value=candidates([hit(1, .8)])):
            bm25 = api.search(api.SearchRequest(query="chicken", mode="bm25"))
            vector = api.search(api.SearchRequest(query="chicken", mode="vector"))
        self.assertEqual(bm25["results"][0]["score"], .8)
        self.assertIsNone(bm25["timings"]["rrf_ms"])
        self.assertIsNone(bm25["timings"]["vector_recall_ms"])
        self.assertAlmostEqual(vector["results"][0]["semantic_similarity"], .6)

    def test_invalid_configuration(self):
        for config in ({"rrf_k": 0}, {"rrf_k": True}, {"bm25_candidates": 1},
                       {"vector_num_candidates": 20}, {"branch_timeout_seconds": 0},
                       {"execution": "fake"}, {"query": "   "}):
            with self.subTest(config=config), self.assertRaises(ValidationError):
                api.SearchRequest(**{"query": "chicken", **config})

    def test_normal_and_streaming_api_agree(self):
        client = TestClient(api.app)
        with patch.object(api, "retrieve_candidates", return_value=candidates([hit(1)])):
            normal = client.post("/recipes/search", json={"query": "chicken"})
            stream = client.post("/api/search/stream", json={"query": "chicken"})
        self.assertEqual(normal.status_code, 200)
        frames = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
        streamed = next(frame for frame in frames if frame["type"] == "result")
        for key in ("results", "candidate_counts", "effective_filters", "rrf", "effective_mode"):
            self.assertEqual(normal.json()[key], streamed[key])
        self.assertIn("search_total_ms", streamed["timings"])
        self.assertIn("backend_request_ms", streamed["timings"])

    def test_api_validation_and_failure(self):
        client = TestClient(api.app)
        self.assertEqual(client.post("/recipes/search", json={"query": "x", "rrf_k": 0}).status_code, 422)
        with patch.object(api, "retrieve_candidates", side_effect=RuntimeError):
            self.assertEqual(client.post("/recipes/search", json={"query": "x"}).status_code, 502)
            stream = client.post("/api/search/stream", json={"query": "x"})
        self.assertIn('"type": "error"', stream.text)


class ExecutionTests(unittest.TestCase):
    def test_progress_reports_fast_vector_before_slow_bm25(self):
        vector_reported = threading.Event()
        events = []

        def slow_bm25():
            if not vector_reported.wait(timeout=1):
                raise RuntimeError("Vector completion was hidden behind BM25")
            return candidates([])

        def progress(name, status, elapsed):
            events.append((name, status))
            if name == "vector" and status == "complete":
                vector_reported.set()

        outcomes = execute_branches({"bm25": slow_bm25, "vector": lambda: candidates([])},
                                    execution="parallel", timeout_seconds=2, on_progress=progress)
        self.assertEqual(outcomes["bm25"].status, "complete")
        self.assertLess(events.index(("vector", "complete")), events.index(("bm25", "complete")))

    def test_deadline_does_not_wait_for_running_worker_and_no_late_progress(self):
        release = threading.Event()
        events = []

        def blocked():
            release.wait(timeout=2)
            return candidates([hit(1)])

        started = time.perf_counter()
        try:
            outcome = execute_branches({"bm25": lambda: candidates([hit(2)]), "vector": blocked},
                                       execution="parallel", timeout_seconds=.05,
                                       on_progress=lambda *args: events.append(args))
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 1)
            self.assertEqual(outcome["bm25"].status, "complete")
            self.assertEqual(outcome["vector"].status, "timeout")
            count = len(events)
        finally:
            release.set()
        time.sleep(.02)
        self.assertEqual(len(events), count)

    def test_serial_starts_second_branch_after_first_finishes(self):
        events = []

        def branch(name):
            events.append(name)
            return candidates([])

        execute_branches({"bm25": lambda: branch("bm25"), "vector": lambda: branch("vector")},
                         execution="serial", timeout_seconds=1,
                         on_progress=lambda name, status, elapsed: events.append(f"{name}:{status}"))
        self.assertLess(events.index("bm25:complete"), events.index("vector:running"))

    def test_capacity_rejection_is_explicit(self):
        with patch("retrieval_execution.SLOTS") as slots:
            slots.acquire.return_value = False
            result = execute_branches({"bm25": lambda: candidates([])}, execution="parallel",
                                      timeout_seconds=1, on_progress=lambda *args: None)
        self.assertEqual(result["bm25"].error_type, "CapacityExceeded")


if __name__ == "__main__":
    unittest.main()
