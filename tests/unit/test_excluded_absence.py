import unittest
from types import SimpleNamespace as S

from recipe_search.matching.eligibility import apply_semantic, local_checks


class ExcludedAbsenceTests(unittest.TestCase):
    def recipe(self, ingredients):
        return dict(name="Soup", ingredients=ingredients, keywords=[], recipecategory=[])

    def condition(self, role="excluded", kind="ingredient", name="onion"):
        return dict(constraint_id="hard-1", kind=kind, name=name, role=role)

    def test_unlisted_specific_passes_without_semantic_call(self):
        c = local_checks(self.recipe(["beef", "seasoning blend"]), [self.condition()])[0]
        self.assertEqual(c["decision"], "pass")
        self.assertTrue(c["assumed_absent"])
        self.assertFalse(c["semantic_required"])

    def test_recorded_onion_still_fails(self):
        for ingredient in ["onion", "onion powder", "scallions", "onion-containing seasoning"]:
            with self.subTest(ingredient=ingredient):
                self.assertEqual(
                    local_checks(self.recipe([ingredient]), [self.condition()])[0]["decision"],
                    "fail",
                )

    def test_required_and_missing_list_stay_unknown(self):
        self.assertEqual(
            local_checks(self.recipe(["beef"]), [self.condition(role="required")])[0]["decision"],
            "unknown",
        )
        self.assertEqual(
            local_checks(self.recipe([]), [self.condition()])[0]["decision"], "unknown"
        )

    def semantic(self, status, role="excluded", evidence=None, ingredients=None):
        r = self.recipe(ingredients if ingredients is not None else ["seasoning blend"])
        checks = local_checks(r, [self.condition(role=role, kind="category", name="vegetable")])
        a = S(
            recipe_id="1",
            checks=[
                S(
                    constraint_id="hard-1",
                    status=status,
                    evidence=evidence or [],
                    reason="Model classification",
                )
            ],
        )
        apply_semantic(a, r, checks, checks[:])
        return checks[0]

    def test_unknown_exclusion_assumes_absent(self):
        c = self.semantic("unknown")
        self.assertEqual(c["decision"], "pass")
        self.assertTrue(c["assumed_absent"])
        self.assertEqual(c["model_status"], "unknown")

    def test_negative_exclusion_not_promoted_to_unknown_for_blends(self):
        self.assertEqual(self.semantic("not_matched")["decision"], "pass")
        self.assertEqual(self.semantic("not_matched", role="required")["decision"], "unknown")

    def test_category_member_still_excluded(self):
        self.assertEqual(
            self.semantic("matched", evidence=["broccoli"], ingredients=["broccoli"])["decision"],
            "fail",
        )
        self.assertEqual(self.semantic("unknown", ingredients=[])["decision"], "unknown")
