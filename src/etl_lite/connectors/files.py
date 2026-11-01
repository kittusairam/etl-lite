"""CSV and Parquet connectors.

All paths are confined to the runtime data root. Writes are atomic: data goes to a temporary
file (created with owner-only permissions) in the target directory and is then renamed into
place, so readers never observe a partially written file.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from etl_lite.config import CsvSource, CsvTarget, ParquetSource, ParquetTarget
from etl_lite.context import RuntimeContext
from etl_lite.exceptions import ExtractionError, LoadError
from etl_lite.security import resolve_within

# Leading characters that make spreadsheet applications treat a cell as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _existing_file(path: Path) -> Path:
    if not path.is_file():
        raise ExtractionError(f"Source file not found: {path}")
    return path


@contextmanager
def _atomic_output(path: Path, mode: str) -> Iterator[Path]:
    if mode == "fail" and path.exists():
        raise LoadError(f"Target already exists and mode is 'fail': {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        yield tmp_path
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _escape_formulas(df: pd.DataFrame) -> pd.DataFrame:
    """Neutralise CSV/formula injection by prefixing risky text cells with a quote."""

    def _escape(value: object) -> object:
        if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
            return "'" + value
        return value

    text_columns = df.select_dtypes(include=["object", "string"]).columns
    if text_columns.empty:
        return df
    escaped = df.copy()
    for column in text_columns:
        escaped[column] = escaped[column].map(_escape)
    return escaped


class CsvReader:
    def __init__(self, config: CsvSource, context: RuntimeContext) -> None:
        self._config = config
        self._path = resolve_within(config.path, context.data_root)

    def describe(self) -> str:
        return f"csv:{self._path}"

    def read(self) -> pd.DataFrame:
        df: pd.DataFrame = pd.read_csv(_existing_file(self._path), **self._config.options)
        return df


class ParquetReader:
    def __init__(self, config: ParquetSource, context: RuntimeContext) -> None:
        self._config = config
        self._path = resolve_within(config.path, context.data_root)

    def describe(self) -> str:
        return f"parquet:{self._path}"

    def read(self) -> pd.DataFrame:
        return pd.read_parquet(_existing_file(self._path), columns=self._config.columns)


class CsvWriter:
    def __init__(self, config: CsvTarget, context: RuntimeContext) -> None:
        self._config = config
        self._path = resolve_within(config.path, context.data_root)

    def describe(self) -> str:
        return f"csv:{self._path}"

    def write(self, df: pd.DataFrame) -> None:
        if self._config.escape_formulas:
            df = _escape_formulas(df)
        with _atomic_output(self._path, self._config.mode) as tmp_path:
            df.to_csv(tmp_path, index=False, **self._config.options)


class ParquetWriter:
    def __init__(self, config: ParquetTarget, context: RuntimeContext) -> None:
        self._config = config
        self._path = resolve_within(config.path, context.data_root)

    def describe(self) -> str:
        return f"parquet:{self._path}"

    def write(self, df: pd.DataFrame) -> None:
        compression = None if self._config.compression == "none" else self._config.compression
        with _atomic_output(self._path, self._config.mode) as tmp_path:
            df.to_parquet(tmp_path, index=False, compression=compression)
