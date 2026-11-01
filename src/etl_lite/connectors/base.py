"""Connector interfaces."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class Reader(Protocol):
    """Reads a DataFrame from a source."""

    def describe(self) -> str:
        """Human-readable, secret-free description for logs."""
        ...

    def read(self) -> pd.DataFrame: ...


class Writer(Protocol):
    """Writes a DataFrame to a target."""

    def describe(self) -> str:
        """Human-readable, secret-free description for logs."""
        ...

    def write(self, df: pd.DataFrame) -> None: ...
