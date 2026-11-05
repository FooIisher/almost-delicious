import unittest
from pydantic import ValidationError
from recipe_search.matching.constraint_logic import (
    RequiredExpression,
    evaluate,
    validate_references,
)


class SingletonExpressionTests(unittest.TestCase):
    def test_singleton_and_or_normalize_to_leaf(self):
        for op in ("AND", "OR"):
            expr = RequiredExpression.model_validate(
                {
                    "op": op,
                    "ingredient": None,
                    "children": [{"op": "ingredient", "ingredient": "beef", "children": []}],
                }
            )
            self.assertEqual(
                expr.model_dump(), {"op": "ingredient", "ingredient": "beef", "children": []}
            )
            self.assertEqual(evaluate(expr, {"beef": "pass"}), "pass")
            with self.assertRaises(ValueError):
                validate_references(expr, ["chicken"])

    def test_nested_singleton_preserves_group(self):
        def leaf(n):
            return dict(op="ingredient", ingredient=n)

        expr = RequiredExpression.model_validate(
            dict(
                op="AND",
                children=[
                    dict(op="OR", children=[dict(op="AND", children=[leaf("beef"), leaf("rice")])])
                ],
            )
        )
        self.assertEqual(expr.op, "AND")
        self.assertEqual(len(expr.children), 2)
        self.assertEqual(evaluate(expr, {"beef": "pass", "rice": "fail"}), "fail")

    def test_empty_and_malformed_groups_still_rejected(self):
        for data in [
            dict(op="AND", children=[]),
            dict(op="OR", ingredient="beef", children=[dict(op="ingredient", ingredient="beef")]),
        ]:
            with self.assertRaises(ValidationError):
                RequiredExpression.model_validate(data)
