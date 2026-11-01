"""SQL database connectors (SQLite and any SQLAlchemy-supported database).

* Credentials are kept in ``SecretStr`` and only rendered masked in logs and errors.
* Bound parameters are hidden from SQLAlchemy error messages (``hide_parameters``).
* SQLite database files must live under the runtime data root.
* Source queries must be a single read-only statement and accept bound ``params``.
* Loads run inside a transaction, so a failed load leaves the target unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from etl_lite.config import SqlSource, SqlTarget
from etl_lite.context import RuntimeContext
from etl_lite.exceptions import ExtractionError, LoadError, SecurityError
from etl_lite.security import mask_db_url, parse_db_url, resolve_within

_IN_MEMORY = frozenset({"", ":memory:"})


def _confined_url(raw_url: str, context: RuntimeContext) -> URL:
    url = parse_db_url(raw_url)
    if url.get_backend_name() != "sqlite":
        return url
    if url.query:
        raise SecurityError("Query parameters are not permitted in SQLite URLs.")
    database = url.database
    if database is None or database in _IN_MEMORY:
        return url
    return url.set(database=str(resolve_within(database, context.data_root)))


@contextmanager
def _engine(url: URL) -> Iterator[Engine]:
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()


def _describe_error(exc: SQLAlchemyError) -> str:
    original = getattr(exc, "orig", None)
    return f"{type(exc).__name__}: {original if original is not None else exc}"


class SqlReader:
    def __init__(self, config: SqlSource, context: RuntimeContext) -> None:
        self._config = config
        self._url = _confined_url(config.db_url.get_secret_value(), context)

    def describe(self) -> str:
        target = self._config.table if self._config.table else "query"
        return f"{self._config.type}:{mask_db_url(self._url)} [{target}]"

    def read(self) -> pd.DataFrame:
        config = self._config
        try:
            with _engine(self._url) as engine, engine.connect() as connection:
                if config.query is not None:
                    return pd.read_sql(text(config.query), connection, params=config.params)
                # SqlSource validation guarantees 'table' is set when 'query' is not.
                table = cast(str, config.table)
                return pd.read_sql_table(table, connection, schema=config.db_schema)
        except SQLAlchemyError as exc:
            raise ExtractionError(f"Database read failed: {_describe_error(exc)}") from None


class SqlWriter:
    def __init__(self, config: SqlTarget, context: RuntimeContext) -> None:
        self._config = config
        self._url = _confined_url(config.db_url.get_secret_value(), context)

    def describe(self) -> str:
        return f"{self._config.type}:{mask_db_url(self._url)} [{self._config.table}]"

    def write(self, df: pd.DataFrame) -> None:
        config = self._config
        try:
            with _engine(self._url) as engine, engine.begin() as connection:
                df.to_sql(
                    config.table,
                    connection,
                    schema=config.db_schema,
                    if_exists=config.mode,
                    index=False,
                    chunksize=config.chunksize,
                )
        except ValueError as exc:
            # pandas raises ValueError when the table exists and mode is 'fail'.
            raise LoadError(str(exc)) from None
        except SQLAlchemyError as exc:
            raise LoadError(f"Database write failed: {_describe_error(exc)}") from None
