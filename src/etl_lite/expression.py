"""Safe row-filter expressions.

Filter conditions use a pandas-``query``-like syntax (``score > 80 and city in ['Oslo', 'Rome']``)
but are *never* passed to ``eval``, ``DataFrame.query`` or ``DataFrame.eval``. The text is parsed
with :mod:`ast`, checked against a whitelist of node types, and evaluated by walking the tree.
Function calls, attribute access, subscripts, arithmetic and variable references other than
column names are rejected, so a configuration file cannot execute code.

Supported syntax:
    * comparisons: ``==  !=  <  <=  >  >=`` (chains such as ``1 < x <= 5`` are allowed)
    * membership: ``col in [..]``, ``col not in [..]``
    * boolean logic: ``and  or  not`` and their pandas spellings ``&  |  ~``
    * literals: strings, numbers, ``True``, ``False``, ``None`` (``col == None`` tests for nulls)
    * column names with spaces or symbols in backticks: ``\\`unit price\\` > 10``
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import reduce
from typing import Any

import pandas as pd

from etl_lite.exceptions import TransformationError

MAX_EXPRESSION_LENGTH = 2_000
MAX_EXPRESSION_NODES = 250

_BACKTICK_COLUMN = re.compile(r"`([^`]+)`")

_COMPARATORS: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.BinOp,
    ast.BitAnd,
    ast.BitOr,
    ast.UnaryOp,
    ast.Not,
    ast.Invert,
    ast.USub,
    ast.UAdd,
    ast.Compare,
    ast.In,
    ast.NotIn,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    *_COMPARATORS,
)

_LITERAL_TYPES = (str, int, float, bool, type(None))


@dataclass(frozen=True)
class FilterExpression:
    """A validated filter condition that can be evaluated against DataFrames."""

    source: str
    _tree: ast.Expression
    _columns: dict[str, str]

    @classmethod
    def parse(cls, source: str) -> FilterExpression:
        """Parse and validate ``source``.

        Raises:
            ValueError: if the expression is empty, too large, malformed or uses unsupported syntax.
        """
        if not source or not source.strip():
            raise ValueError("Filter condition must not be empty.")
        if len(source) > MAX_EXPRESSION_LENGTH:
            raise ValueError(f"Filter condition exceeds {MAX_EXPRESSION_LENGTH} characters.")

        columns: dict[str, str] = {}

        def _placeholder(match: re.Match[str]) -> str:
            name = f"__etl_col_{len(columns)}__"
            columns[name] = match.group(1)
            return name

        rewritten = _BACKTICK_COLUMN.sub(_placeholder, source)
        try:
            tree = ast.parse(rewritten.strip(), mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid filter condition syntax: {exc.msg}.") from None

        nodes = list(ast.walk(tree))
        if len(nodes) > MAX_EXPRESSION_NODES:
            raise ValueError("Filter condition is too complex.")
        for node in nodes:
            if not isinstance(node, _ALLOWED_NODES):
                raise ValueError(
                    f"Unsupported syntax in filter condition: {type(node).__name__}. "
                    "Only comparisons, 'in', boolean logic, column names and literals are allowed."
                )
            if isinstance(node, ast.Constant) and not isinstance(node.value, _LITERAL_TYPES):
                raise ValueError(f"Unsupported literal in filter condition: {node.value!r}.")
            if isinstance(node, ast.List | ast.Tuple) and not all(
                _is_literal(element) for element in node.elts
            ):
                raise ValueError("Lists in filter conditions may only contain literals.")
        return cls(source=source, _tree=tree, _columns=columns)

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        """Return a boolean mask selecting the rows of ``df`` that satisfy the condition."""
        result = _Evaluator(df, self._columns).mask(self._tree.body)
        return result.fillna(False).astype(bool)


def _is_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        node = node.operand
    return isinstance(node, ast.Constant)


class _Evaluator:
    def __init__(self, df: pd.DataFrame, columns: dict[str, str]) -> None:
        self._df = df
        self._columns = columns

    def mask(self, node: ast.expr) -> pd.Series:
        value = self.value(node)
        if isinstance(value, bool):
            return pd.Series(value, index=self._df.index, dtype=bool)
        if isinstance(value, pd.Series) and pd.api.types.is_bool_dtype(value.dtype):
            return value
        raise TransformationError("Filter condition must evaluate to true/false for each row.")

    def value(self, node: ast.expr) -> Any:
        match node:
            case ast.BoolOp(op=ast.And(), values=values):
                return reduce(operator.and_, (self.mask(v) for v in values))
            case ast.BoolOp(op=ast.Or(), values=values):
                return reduce(operator.or_, (self.mask(v) for v in values))
            case ast.BinOp(left=left, op=ast.BitAnd(), right=right):
                return self.mask(left) & self.mask(right)
            case ast.BinOp(left=left, op=ast.BitOr(), right=right):
                return self.mask(left) | self.mask(right)
            case ast.UnaryOp(op=ast.Not() | ast.Invert(), operand=operand):
                return ~self.mask(operand)
            case ast.UnaryOp(op=ast.USub(), operand=operand):
                return -self.value(operand)
            case ast.UnaryOp(op=ast.UAdd(), operand=operand):
                return self.value(operand)
            case ast.Compare(left=left, ops=ops, comparators=comparators):
                return self._compare_chain(left, ops, comparators)
            case ast.Name(id=name):
                return self._column(self._columns.get(name, name))
            case ast.Constant(value=value):
                return value
            case ast.List(elts=elements) | ast.Tuple(elts=elements):
                return [self.value(element) for element in elements]
        raise TransformationError(f"Unsupported filter syntax: {type(node).__name__}.")

    def _column(self, name: str) -> pd.Series:
        if name not in self._df.columns:
            raise TransformationError(f"Unknown column '{name}' in filter condition.")
        return self._df[name]

    def _compare_chain(self, left: ast.expr, ops: list[ast.cmpop], comparators: list[ast.expr]) -> pd.Series:
        lhs = self.value(left)
        results = []
        for op, comparator in zip(ops, comparators, strict=True):
            rhs = self.value(comparator)
            results.append(self._compare(op, lhs, rhs))
            lhs = rhs
        return reduce(operator.and_, results)

    @staticmethod
    def _compare(op: ast.cmpop, lhs: Any, rhs: Any) -> pd.Series:
        if isinstance(op, ast.In | ast.NotIn):
            if not isinstance(lhs, pd.Series) or not isinstance(rhs, list):
                raise TransformationError("'in' requires a column on the left and a list on the right.")
            members = lhs.isin(rhs)
            return ~members if isinstance(op, ast.NotIn) else members
        if isinstance(op, ast.Eq | ast.NotEq) and (lhs is None or rhs is None):
            series = rhs if lhs is None else lhs
            if not isinstance(series, pd.Series):
                raise TransformationError("Comparisons with None require a column.")
            return series.isna() if isinstance(op, ast.Eq) else series.notna()
        if not isinstance(lhs, pd.Series) and not isinstance(rhs, pd.Series):
            raise TransformationError("Each comparison must reference at least one column.")
        result: pd.Series = _COMPARATORS[type(op)](lhs, rhs)
        return result
