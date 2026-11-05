import unittest
from recipe_search.llm.extraction_schema import Bound
from recipe_search.llm.gpt_intent_service import normalize_approximate_time


class Extraction:
    def __init__(self, bounds):
        self.bounds = bounds

    def model_copy(self, update):
        return Extraction(update["bounds"])


class ApproximateTimeTests(unittest.TestCase):
    def bound(self, **kw):
        return Bound(
            **dict(
                field="total_time",
                operator="lte",
                value=30,
                unit="minutes",
                basis="not_applicable",
                evidence="around 30 min",
                **kw,
            )
        )

    def test_inclusive_range(self):
        r = normalize_approximate_time(Extraction([self.bound()]))
        self.assertEqual([(b.operator, b.value) for b in r.bounds], [("gte", 22.5), ("lte", 37.5)])
        self.assertEqual(r.bounds[0].evidence, "around 30 min")

    def test_already_two_bounds_deduplicates(self):
        r = normalize_approximate_time(Extraction([self.bound(), self.bound()]))
        self.assertEqual(len(r.bounds), 2)

    def test_explicit_upper_unchanged(self):
        b = self.bound().model_copy(update={"evidence": "under 30 minutes", "operator": "lt"})
        self.assertEqual(normalize_approximate_time(Extraction([b])).bounds, [b])
