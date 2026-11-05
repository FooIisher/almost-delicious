import unittest
from types import SimpleNamespace as S

from recipe_search.matching.eligibility import apply_semantic


class EvidencePrefixTests(unittest.TestCase):
    def check(self, evidence, kind="dish_type", name="Chicken dinner", status="matched"):
        recipe = dict(
            ingredients=["fresh broccoli florets"],
            name=name,
            keywords=["easy"],
            recipecategory=["one dish meal"],
        )
        checks = [
            dict(
                constraint_id="hard-6",
                kind=kind,
                role="required",
                source="local",
                semantic_required=True,
            )
        ]
        assessment = S(
            recipe_id="56589",
            checks=[
                S(
                    constraint_id="hard-6",
                    status=status,
                    evidence=[evidence],
                    reason="Recorded field",
                )
            ],
        )
        apply_semantic(assessment, recipe, checks, checks[:])
        return checks[0]["evidence"]

    def test_prefix(self):
        self.assertEqual(self.check("recipecategory: one dish meal"), ["one dish meal"])
        self.assertEqual(
            self.check("ingredients: fresh broccoli florets", "ingredient"),
            ["fresh broccoli florets"],
        )
        self.assertEqual(self.check("ONE DISH MEAL"), ["one dish meal"])

    def test_invalid(self):
        for evidence, kind in [
            ("keywords: one dish meal", "dish_type"),
            ("recipecategory: one dish meal", "ingredient"),
            ("ingredients: broccoli", "ingredient"),
            ("ingredients: invented", "ingredient"),
        ]:
            with self.subTest(evidence=evidence):
                self.assertEqual(self.check(evidence, kind), [])

    def test_html_encoded_recipe_name(self):
        source = "Chicken, Broccoli and Rice &quot;divan&quot;"
        self.assertEqual(self.check('Chicken, Broccoli and Rice "divan"', name=source), [source])
        self.assertEqual(
            self.check('name: Chicken, Broccoli and Rice "divan"', name=source), [source]
        )
        self.assertEqual(self.check("Chicken, Broccoli and Rice", name=source), [])

    def test_html_space_and_ampersand(self):
        source = "Chicken &amp; Broccoli&nbsp; Soup"
        self.assertEqual(self.check("Chicken & Broccoli Soup", name=source), [source])

    def test_title_can_explain_unknown_ingredient_only(self):
        self.assertEqual(
            self.check(
                "Red Pepper Alfredo", "ingredient", name="Red Pepper Alfredo", status="unknown"
            ),
            ["Red Pepper Alfredo"],
        )
        for status in ("matched", "not_matched"):
            self.assertEqual(
                self.check(
                    "Red Pepper Alfredo", "ingredient", name="Red Pepper Alfredo", status=status
                ),
                [],
            )

    def test_dish_type_instruction_evidence_and_invalid_check_isolation(self):
        recipe = dict(
            name="Fruit dessert",
            ingredients=["banana"],
            keywords=[],
            recipecategory=[],
            instructions=["Serve as a fruit salad."],
        )
        checks = [
            dict(
                constraint_id="hard-1",
                kind="dish_type",
                name="salad",
                role="required",
                source="local",
                semantic_required=True,
            ),
            dict(
                constraint_id="hard-2",
                kind="ingredient",
                name="banana",
                role="excluded",
                source="local",
                semantic_required=True,
            ),
        ]
        assessment = S(
            recipe_id="1",
            checks=[
                S(
                    constraint_id="hard-1",
                    status="matched",
                    evidence=["Serve as a fruit salad."],
                    reason="Recorded preparation.",
                ),
                S(
                    constraint_id="hard-2",
                    status="matched",
                    evidence=["invented banana"],
                    reason="Invalid.",
                ),
            ],
        )
        warnings = apply_semantic(assessment, recipe, checks, checks[:])
        self.assertEqual(checks[0]["decision"], "pass")
        self.assertEqual(checks[1]["decision"], "unknown")
        self.assertFalse(checks[1]["assumed_absent"])
        self.assertFalse(checks[1]["semantic_required"])
        self.assertEqual(checks[1]["invalid_evidence"], ["invented banana"])
        self.assertIn("hard-2", warnings[0])
        self.assertIn("downgraded", warnings[0])

    def test_instruction_excerpt_resolves_to_recorded_step(self):
        step = "Heat the wok. Add half the marinated chicken with the marinade and stir-fry for 1 minute. Then set aside."
        recipe = dict(
            name="Ginger chicken",
            ingredients=["chicken"],
            keywords=[],
            recipecategory=[],
            instructions=[step],
        )
        for kind in ("dish_name", "dish_type"):
            checks = [
                dict(
                    constraint_id="hard-1",
                    kind=kind,
                    name="stir fry",
                    role="required",
                    source="local",
                    semantic_required=True,
                )
            ]
            assessment = S(
                recipe_id="1",
                checks=[
                    S(
                        constraint_id="hard-1",
                        status="matched",
                        evidence=[
                            "Add half the marinated chicken with the marinade and stir-fry for 1 minute."
                        ],
                        reason="Recorded stir frying.",
                    )
                ],
            )
            self.assertEqual(apply_semantic(assessment, recipe, checks, checks[:]), [])
            self.assertEqual(checks[0]["evidence"], [step])
            self.assertEqual(checks[0]["decision"], "pass")
