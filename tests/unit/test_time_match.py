import unittest

from recipe_search.matching.time_match import time_constraint_matches


class TimeMatchTests(unittest.TestCase):
    def settings(self, op="lte", value=15):
        return {"numeric_filters": [{"field": "total_time", "operator": op, "value": value}]}

    def test_strict_and_inclusive(self):
        for op, expected in [
            ("lt", "not_met"),
            ("lte", "met"),
            ("eq", "met"),
            ("gt", "not_met"),
            ("gte", "met"),
        ]:
            check = time_constraint_matches({"total_time_minutes": 15}, self.settings(op))[0]
            self.assertEqual(check["status"], expected)
            self.assertFalse(check["scoring"])

    def test_missing_invalid_and_outside(self):
        for value in [None, True, float("nan"), -1]:
            self.assertEqual(
                time_constraint_matches({"total_time_minutes": value}, self.settings())[0][
                    "status"
                ],
                "missing",
            )
        self.assertEqual(
            time_constraint_matches({"total_time_minutes": 20}, self.settings())[0]["status"],
            "not_met",
        )

    def test_no_explicit_filter_and_legacy(self):
        self.assertEqual(time_constraint_matches({"total_time_minutes": 15}, {}), [])
        self.assertEqual(
            len(
                time_constraint_matches(
                    {"total_time_minutes": 15}, {**self.settings(), "max_total_time_minutes": 15}
                )
            ),
            1,
        )
        self.assertEqual(
            time_constraint_matches({"total_time_minutes": 30}, {"cook_time": "less_30"})[0][
                "status"
            ],
            "not_met",
        )
