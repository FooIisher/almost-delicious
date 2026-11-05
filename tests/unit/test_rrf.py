import copy
import unittest

from recipe_search.retrieval.rrf import recipe_id, reciprocal_rank_fusion


def hit(identifier, score=1.0, **source):
    return {
        "_id": str(identifier),
        "_score": score,
        "_source": {"recipeid": identifier, "name": f"Recipe {identifier}", **source},
    }


class RRFTests(unittest.TestCase):
    def test_hand_calculated_overlap_and_missing_branch(self):
        rows = reciprocal_rank_fusion([hit("a"), hit("b")], [hit("b"), hit("c")], k=60)
        self.assertEqual([row["recipe_id"] for row in rows], ["b", "a", "c"])
        self.assertAlmostEqual(rows[0]["rrf_score"], 1 / 62 + 1 / 61)
        self.assertEqual((rows[0]["bm25_rank"], rows[0]["vector_rank"]), (2, 1))
        self.assertIsNone(rows[1]["vector_rank"])
        self.assertEqual(rows[1]["vector_contribution"], 0)

    def test_duplicate_ids_are_counted_once_and_ranks_are_contiguous(self):
        rows = reciprocal_rank_fusion([hit(1), hit("1", 100), hit(2)], [hit("1")])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["rrf_score"], 2 / 2)
        self.assertEqual(rows[1]["bm25_rank"], 2)

    def test_ties_use_best_rank_then_id_and_ignore_raw_scores(self):
        rows = reciprocal_rank_fusion([hit("b", 1000), hit("a", 0.001)], [hit("a"), hit("b")])
        self.assertEqual([row["recipe_id"] for row in rows], ["a", "b"])

    def test_best_rank_breaks_equal_score_before_id(self):
        # k=1: 1/3 = 1/4 + 1/12. z's best rank 2 beats a's rank 3.
        lexical = [hit(f"l{i}") for i in range(1, 12)]
        vector = [hit(f"v{i}") for i in range(1, 12)]
        lexical[1] = hit("z")
        lexical[2] = hit("a")
        vector[10] = hit("a")
        rows = reciprocal_rank_fusion(lexical, vector, k=1, size=30)
        ids = [row["recipe_id"] for row in rows]
        self.assertLess(ids.index("z"), ids.index("a"))

    def test_boosts_change_ranking_and_contributions(self):
        rows = reciprocal_rank_fusion([hit("a")], [hit("b")], bm25_boost=1, vector_boost=3)
        self.assertEqual([row["recipe_id"] for row in rows], ["b", "a"])
        self.assertEqual(rows[0]["vector_contribution"], 1.5)
        self.assertEqual(rows[1]["bm25_contribution"], 0.5)
        for invalid in (0, -1, float("inf"), float("nan"), True):
            with self.assertRaises(ValueError):
                reciprocal_rank_fusion([], [], bm25_boost=invalid)

    def test_inputs_unchanged_and_repeated_results_identical(self):
        lexical = [hit("a"), hit("b")]
        vector = [hit("b"), hit("a")]
        original = copy.deepcopy((lexical, vector))
        first = reciprocal_rank_fusion(lexical, vector)
        for _ in range(20):
            self.assertEqual(first, reciprocal_rank_fusion(lexical, vector))
        self.assertEqual((lexical, vector), original)

    def test_empty_single_branch_and_top_n(self):
        self.assertEqual(reciprocal_rank_fusion([], []), [])
        rows = reciprocal_rank_fusion([], [hit(2), hit(1)], size=1)
        self.assertEqual(rows[0]["recipe_id"], "2")
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["bm25_contribution"], 0)

    def test_id_fallback_and_invalid_inputs(self):
        self.assertEqual(recipe_id({"_id": "fallback"}), "fallback")
        for invalid in ({}, {"_source": {"recipeid": True}}, {"_source": {"recipeid": ""}}):
            with self.assertRaises(ValueError):
                recipe_id(invalid)
        for invalid in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                reciprocal_rank_fusion([], [], k=invalid)
        with self.assertRaises(ValueError):
            reciprocal_rank_fusion([], [], size=0)


if __name__ == "__main__":
    unittest.main()
