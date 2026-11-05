import unittest

from recipe_search.api.search import SearchRequest
from recipe_search.ranking.preference_ranking import rerank


class PreferenceRankingTests(unittest.TestCase):
    def test_rating_bonus_exact_values_and_missing(self):
        for rating, factor in [
            (5, 1),
            (4, 0.8),
            (3, 0.6),
            (4.5, 0.9),
            (2, 0),
            (None, 0),
            ("5", 0),
            (True, 0),
            (float("nan"), 0),
        ]:
            rows = self.rows()
            rows[0]["hit"]["_source"]["aggregatedrating"] = rating
            result = rerank(
                rows, SearchRequest(query="soup", rating_boost=0.2, preference_lambda=0)
            )
            row = next(x for x in result if x["rrf_rank"] == 1)
            self.assertAlmostEqual(row["rating_bonus"], 0.2 * factor)
            self.assertAlmostEqual(row["final_score"], row["normalized_rrf"] + 0.2 * factor)

    def test_rating_changes_order_and_zero_disables(self):
        rows = self.rows()
        rows[1]["hit"]["_source"]["aggregatedrating"] = 5
        request = SearchRequest(query="soup", rrf_k=1, vector_boost=5, rating_boost=0.2)
        self.assertEqual(rerank(rows, request)[0]["rrf_rank"], 2)
        rows = self.rows()
        rows[1]["hit"]["_source"]["aggregatedrating"] = 5
        self.assertEqual(
            rerank(rows, request.model_copy(update={"rating_boost": 0}))[0]["rrf_rank"], 1
        )

    def test_flavor_is_ranking_only_and_explained(self):
        rows = self.rows()
        rows[1]["hit"]["_source"]["name"] = "Spicy chicken stir fry"
        result = rerank(rows, SearchRequest(query="chicken stir fry", preference_flavor=["spicy"]))
        evidence = next(
            e
            for r in result
            if r["rrf_rank"] == 2
            for e in r["preference_evidence"]
            if e["group"] == "flavor"
        )
        self.assertEqual(evidence["matched"], ["spicy"])
        self.assertGreater(evidence["final_contribution"], 0)

    def rows(self):
        return [
            dict(
                rank=1, rrf_score=2.4, hit={"_source": {"ingredients": ["onion"], "keywords": []}}
            ),
            dict(
                rank=2,
                rrf_score=2.1,
                hit={
                    "_source": {
                        "ingredients": ["lotus root"],
                        "keywords": ["chinese"],
                        "recipecategory": ["chinese"],
                    }
                },
            ),
        ]

    def test_formula_and_rank_change(self):
        request = SearchRequest(
            query="soup",
            rrf_k=1,
            vector_boost=5,
            preference_prefer=["lotus root"],
            preference_cuisine=["chinese"],
            preference_avoid=["onion"],
        )
        rows = rerank(self.rows(), request)
        self.assertEqual(rows[0]["rrf_rank"], 2)
        self.assertAlmostEqual(rows[0]["final_score"], 1.0)
        self.assertAlmostEqual(rows[1]["final_score"], 0.5)
        self.assertEqual(rows[0]["preference_score"], 1)
        self.assertEqual(
            next(e for e in rows[0]["preference_evidence"] if e["group"] == "cuisine")["matched"],
            ["chinese"],
        )

    def test_zero_lambda_restores_order(self):
        rows = rerank(
            self.rows(),
            SearchRequest(
                query="soup",
                rrf_k=1,
                vector_boost=5,
                preference_lambda=0,
                preference_avoid=["onion"],
            ),
        )
        self.assertEqual([x["rrf_rank"] for x in rows], [1, 2])

    def test_missing_tags_neutral_and_exact(self):
        rows = self.rows()
        rows[0]["hit"]["_source"]["keywords"] = ["clear soup"]
        result = rerank(
            rows,
            SearchRequest(query="soup", rrf_k=1, vector_boost=5, preference_dish_type=["soup"]),
        )
        self.assertEqual(result[0]["preference_score"], 1)
        self.assertEqual(result[1]["preference_score"], 0)

    def test_weights_zero_and_dish_priority(self):
        rows = self.rows()
        rows[0]["hit"]["_source"]["keywords"] = ["soup"]
        request = SearchRequest(
            query="soup",
            rrf_k=1,
            vector_boost=5,
            preference_dish_type=["soup"],
            preference_cuisine=["chinese"],
            preference_weight_dish_type=3,
            preference_weight_cuisine=1,
        )
        result = rerank(rows, request)
        self.assertAlmostEqual(result[0]["preference_score"], 0.75)
        self.assertAlmostEqual(result[1]["preference_score"], 0.25)
        zero = rerank(
            self.rows(),
            SearchRequest(
                query="soup",
                rrf_k=1,
                vector_boost=5,
                preference_cuisine=["chinese"],
                preference_weight_cuisine=0,
                preference_avoid=["onion"],
                preference_weight_avoid=0,
            ),
        )
        self.assertTrue(all(r["preference_score"] == 0 for r in zero))

    def test_avoid_weight_scales_penalty(self):
        result = rerank(
            self.rows(),
            SearchRequest(
                query="soup",
                rrf_k=1,
                vector_boost=5,
                preference_avoid=["onion"],
                preference_weight_avoid=2,
            ),
        )
        onion = next(r for r in result if r["rrf_rank"] == 1)
        self.assertEqual(onion["preference_score"], -2)

    def test_healthy_missing_and_boundaries(self):
        rows = self.rows()
        rows[0]["hit"]["_source"].update(
            proteincontent=20,
            sugarcontent=5,
            fatcontent=3,
            cholesterolcontent=20,
            sodiumcontent=140,
        )
        result = rerank(rows, SearchRequest(query="x", preference_healthy=["healthy"]))
        good = next(r for r in result if r["rrf_rank"] == 1)
        missing = next(r for r in result if r["rrf_rank"] == 2)
        self.assertEqual(good["preference_score"], 1)
        self.assertEqual(missing["preference_score"], 0)
        self.assertTrue(
            all(c["status"] == "missing" for c in missing["preference_evidence"][0]["checks"])
        )

    def test_quick_and_easy_do_not_infer_from_quick_breads(self):
        rows = self.rows()
        rows[0]["hit"]["_source"].update(total_time_minutes=30, keywords=["easy"])
        rows[1]["hit"]["_source"].update(total_time_minutes=31, keywords=["quick breads"])
        result = rerank(
            rows,
            SearchRequest(query="x", preference_quick=["quick", "fast"], preference_easy=["easy"]),
        )
        self.assertEqual(next(r for r in result if r["rrf_rank"] == 1)["preference_score"], 1)
        self.assertEqual(next(r for r in result if r["rrf_rank"] == 2)["preference_score"], 0)
