"""Connector registry.

To add a connector, define its source/target config model in :mod:`etl_lite.config`, implement
the :class:`~etl_lite.connectors.base.Reader` or :class:`~etl_lite.connectors.base.Writer`
protocol, and register the class below.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from etl_lite.config import CsvSource, CsvTarget, ParquetSource, ParquetTarget, SqlSource, SqlTarget
from etl_lite.connectors.base import Reader, Writer
from etl_lite.connectors.files import CsvReader, CsvWriter, ParquetReader, ParquetWriter
from etl_lite.connectors.sql import SqlReader, SqlWriter
from etl_lite.context import RuntimeContext
from etl_lite.exceptions import ConfigurationError

_READERS: dict[type[Any], Callable[[Any, RuntimeContext], Reader]] = {
    CsvSource: CsvReader,
    ParquetSource: ParquetReader,
    SqlSource: SqlReader,
}

_WRITERS: dict[type[Any], Callable[[Any, RuntimeContext], Writer]] = {
    CsvTarget: CsvWriter,
    ParquetTarget: ParquetWriter,
    SqlTarget: SqlWriter,
}


def build_reader(config: Any, context: RuntimeContext) -> Reader:
    factory = _READERS.get(type(config))
    if factory is None:
        raise ConfigurationError(f"No reader registered for {type(config).__name__}.")
    return factory(config, context)


def build_writer(config: Any, context: RuntimeContext) -> Writer:
    factory = _WRITERS.get(type(config))
    if factory is None:
        raise ConfigurationError(f"No writer registered for {type(config).__name__}.")
    return factory(config, context)


__all__ = ["Reader", "Writer", "build_reader", "build_writer"]
