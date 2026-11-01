"""Transformation steps.

Each step type in :mod:`etl_lite.config` maps to a handler here. To add a transformation,
define its config model, add it to ``TransformationConfig`` and register a handler below.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import pandas as pd

from etl_lite.config import DeduplicateStep, DropStep, FilterStep, RenameStep, SelectStep
from etl_lite.exceptions import ETLError, TransformationError
from etl_lite.expression import FilterExpression

logger = logging.getLogger(__name__)


def _require_columns(df: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise TransformationError(f"Column(s) not found: {', '.join(missing)}.")


def _select(df: pd.DataFrame, step: SelectStep) -> pd.DataFrame:
    _require_columns(df, step.columns)
    return df.loc[:, step.columns]


def _filter(df: pd.DataFrame, step: FilterStep) -> pd.DataFrame:
    return df.loc[FilterExpression.parse(step.condition).evaluate(df)]


def _rename(df: pd.DataFrame, step: RenameStep) -> pd.DataFrame:
    _require_columns(df, step.mapping)
    return df.rename(columns=step.mapping)


def _drop(df: pd.DataFrame, step: DropStep) -> pd.DataFrame:
    _require_columns(df, step.columns)
    return df.drop(columns=step.columns)


def _deduplicate(df: pd.DataFrame, step: DeduplicateStep) -> pd.DataFrame:
    if step.subset:
        _require_columns(df, step.subset)
    return df.drop_duplicates(subset=step.subset, keep=step.keep)


_HANDLERS: dict[type[Any], Callable[[pd.DataFrame, Any], pd.DataFrame]] = {
    SelectStep: _select,
    FilterStep: _filter,
    RenameStep: _rename,
    DropStep: _drop,
    DeduplicateStep: _deduplicate,
}


def apply_transformations(df: pd.DataFrame, steps: Sequence[Any]) -> pd.DataFrame:
    """Apply ``steps`` in order, wrapping any failure in :class:`TransformationError`."""
    for number, step in enumerate(steps, start=1):
        handler = _HANDLERS.get(type(step))
        if handler is None:
            raise TransformationError(f"No handler registered for step type {type(step).__name__}.")
        rows_before = len(df)
        try:
            df = handler(df, step)
        except ETLError as exc:
            raise TransformationError(f"Step {number} ({step.action}) failed: {exc}") from exc
        except Exception as exc:
            raise TransformationError(
                f"Step {number} ({step.action}) failed: {type(exc).__name__}: {exc}"
            ) from exc
        logger.debug("Step %d (%s): %d -> %d rows", number, step.action, rows_before, len(df))
    return df
