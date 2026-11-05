"""Shared hard-condition expression, normalization and three-valued logic."""

import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


def normalized(value):
    return " ".join(re.findall(r"[^\W_]+", str(value).casefold()))


class RequiredExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["ingredient", "AND", "OR"]
    ingredient: str | None = None
    children: list["RequiredExpression"] = Field(default_factory=list)

    @model_validator(mode="after")
    def structure(self):
        if self.op == "ingredient":
            if not self.ingredient or not self.ingredient.strip() or self.children:
                raise ValueError("Ingredient leaf requires a name and no children")
        else:
            if self.ingredient is not None or not self.children:
                raise ValueError("AND/OR requires children and no ingredient")
            if self.op == "AND":
                self.children = [
                    leaf
                    for child in self.children
                    for leaf in (child.children if child.op == "AND" else [child])
                ]
            # A singleton group is logically identical to its child. Some models
            # emit it even though the canonical schema uses a leaf directly.
            if len(self.children) == 1:
                child = self.children[0]
                self.op, self.ingredient, self.children = (
                    child.op,
                    child.ingredient,
                    list(child.children),
                )

        def size(node, depth=0):
            if depth > 8:
                raise ValueError("Required expression nesting exceeds 8")
            return 1 + sum(size(c, depth + 1) for c in node.children)

        if size(self) > 100:
            raise ValueError("Required expression exceeds 100 nodes")
        return self


def references(expr):
    if expr is None:
        return []
    if isinstance(expr, dict):
        expr = RequiredExpression.model_validate(expr)
    return (
        [expr.ingredient]
        if expr.op == "ingredient"
        else [n for child in expr.children for n in references(child)]
    )


def validate_references(expr, names):
    allowed = {normalized(n) for n in names}
    if any(normalized(n) not in allowed for n in references(expr)):
        raise ValueError(
            "Required expression must reference only this request's required ingredients"
        )


def evaluate(expr, states):
    if expr is None:
        return "pass"
    if isinstance(expr, dict):
        expr = RequiredExpression.model_validate(expr)
    if expr.op == "ingredient":
        return states.get(normalized(expr.ingredient), "unknown")
    values = [evaluate(child, states) for child in expr.children]
    if expr.op == "AND":
        return (
            "fail"
            if "fail" in values
            else "pass"
            if all(s == "pass" for s in values)
            else "unknown"
        )
    return "pass" if "pass" in values else "fail" if all(s == "fail" for s in values) else "unknown"


def combine(states):
    return "fail" if "fail" in states else "unknown" if "unknown" in states else "pass"


def default_expression(names):
    leaves = [RequiredExpression(op="ingredient", ingredient=n) for n in names]
    return (
        None
        if not leaves
        else leaves[0]
        if len(leaves) == 1
        else RequiredExpression(op="OR", children=leaves)
    )


def safe_pushdown(expr, categories, leaf):
    """None means unrestricted, so a category OR concrete cannot be narrowed."""
    if expr is None:
        return None
    if expr.op == "ingredient":
        return None if normalized(expr.ingredient) in categories else leaf(expr.ingredient)
    children = [safe_pushdown(c, categories, leaf) for c in expr.children]
    if expr.op == "OR" and any(c is None for c in children):
        return None
    children = [c for c in children if c is not None]
    if not children:
        return None
    if len(children) == 1:
        return children[0]
    return (
        {"bool": {"filter": children}}
        if expr.op == "AND"
        else {"bool": {"should": children, "minimum_should_match": 1}}
    )
