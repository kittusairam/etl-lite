from pathlib import Path
from typing import Any

import pytest
import yaml

from etl_lite.config import (
    MAX_CONFIG_BYTES,
    CsvSource,
    FilterStep,
    ParquetTarget,
    SqlSource,
    interpolate_env_vars,
    load_config,
    parse_config,
)
from etl_lite.exceptions import ConfigurationError


def minimal(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "source": {"type": "csv", "path": "input.csv"},
        "load": {"type": "parquet", "path": "out.parquet"},
    }
    config.update(overrides)
    return config


def write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_parses_minimal_config() -> None:
    config = parse_config(minimal())
    assert isinstance(config.source, CsvSource)
    assert isinstance(config.load, ParquetTarget)
    assert config.transformations == []
    assert config.name == "etl-job"


def test_null_transformations_means_empty() -> None:
    assert parse_config(minimal(transformations=None)).transformations == []


def test_transformations_are_typed() -> None:
    config = parse_config(minimal(transformations=[{"action": "filter", "condition": "id > 1"}]))
    assert isinstance(config.transformations[0], FilterStep)


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (minimal(unexpected=1), "unexpected"),
        (minimal(source={"type": "excel", "path": "x"}), "source"),
        (minimal(source={"type": "csv", "path": "x", "options": {"engine": "python"}}), "engine"),
        (minimal(source={"type": "csv", "path": "s3://bucket/key.csv"}), "Remote URLs"),
        (minimal(load={"type": "csv", "path": "x", "mode": "upsert"}), "mode"),
        (minimal(transformations=[{"action": "filter", "condition": "__import__('os')"}]), "Unsupported"),
        (minimal(transformations=[{"action": "select", "columns": []}]), "columns"),
        (minimal(name="bad name!"), "name"),
    ],
)
def test_rejects_invalid_configs(config: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        parse_config(config)


def test_sql_source_requires_exactly_one_of_table_or_query() -> None:
    base = {"type": "sqlite", "db_url": "sqlite:///db.sqlite"}
    with pytest.raises(ConfigurationError, match="exactly one"):
        parse_config(minimal(source=base))
    with pytest.raises(ConfigurationError, match="exactly one"):
        parse_config(minimal(source={**base, "table": "t", "query": "SELECT 1"}))


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM users",
        "SELECT 1; DROP TABLE users",
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
        "PRAGMA table_info(users)",
        "ATTACH DATABASE '/tmp/x.db' AS x",
    ],
)
def test_rejects_non_read_only_queries(query: str) -> None:
    source = {"type": "sqlite", "db_url": "sqlite:///db.sqlite", "query": query}
    with pytest.raises(ConfigurationError):
        parse_config(minimal(source=source))


def test_accepts_parameterised_query() -> None:
    source = {
        "type": "sqlite",
        "db_url": "sqlite:///db.sqlite",
        "query": "SELECT * FROM users WHERE id = :id;",
        "params": {"id": 3},
    }
    config = parse_config(minimal(source=source))
    assert isinstance(config.source, SqlSource)
    assert config.source.query == "SELECT * FROM users WHERE id = :id"


@pytest.mark.parametrize("table", ["users; DROP TABLE x", "a.b", "1abc", "name with space"])
def test_rejects_unsafe_table_names(table: str) -> None:
    load = {"type": "sqlite", "db_url": "sqlite:///db.sqlite", "table": table}
    with pytest.raises(ConfigurationError, match="table name"):
        parse_config(minimal(load=load))


def test_sqlite_type_requires_sqlite_url() -> None:
    load = {"type": "sqlite", "db_url": "postgresql://u:p@host/db", "table": "t"}
    with pytest.raises(ConfigurationError, match="sqlite"):
        parse_config(minimal(load=load))


def test_validation_errors_do_not_leak_secrets() -> None:
    load = {"type": "sql", "db_url": "postgresql://user:s3cr3t-pw@host/db", "table": "t", "bogus": 1}
    with pytest.raises(ConfigurationError) as excinfo:
        parse_config(minimal(load=load))
    assert "s3cr3t-pw" not in str(excinfo.value)


def test_db_url_is_secret_in_repr() -> None:
    load = {"type": "sql", "db_url": "postgresql://user:s3cr3t-pw@host/db", "table": "t"}
    assert "s3cr3t-pw" not in repr(parse_config(minimal(load=load)))


# --------------------------------------------------------------------------- env interpolation


def test_interpolation_with_defaults() -> None:
    environ = {"A": "1"}
    assert interpolate_env_vars({"x": ["${A}", "${B:-two}", 3]}, environ) == {"x": ["1", "two", 3]}


def test_missing_env_var_raises() -> None:
    with pytest.raises(ConfigurationError, match="'MISSING'"):
        interpolate_env_vars("${MISSING}", {})


def test_env_values_cannot_inject_yaml(tmp_path: Path) -> None:
    config_file = write_yaml(
        tmp_path / "job.yaml",
        "source:\n  type: csv\n  path: ${SRC}\nload:\n  type: parquet\n  path: out.parquet\n",
    )
    injected = "x.csv\n  options:\n    engine: python"
    config = load_config(config_file, environ={"SRC": injected})
    assert isinstance(config.source, CsvSource)
    assert config.source.path == injected
    assert config.source.options == {}


# --------------------------------------------------------------------------- file loading


def test_load_config_from_file(tmp_path: Path) -> None:
    config_file = write_yaml(tmp_path / "job.yaml", yaml.safe_dump(minimal(name="nightly")))
    assert load_config(config_file).name == "nightly"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(tmp_path / "absent.yaml")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("- just\n- a list\n", "mapping"),
        ("source: [unclosed\n", "Invalid YAML"),
        ("a: &x [1]\nb: *x\n", "aliases"),
        ("!!python/object/apply:os.system ['echo pwned']\n", "Invalid YAML"),
    ],
)
def test_rejects_bad_yaml(tmp_path: Path, content: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_config(write_yaml(tmp_path / "job.yaml", content))


def test_rejects_oversized_file(tmp_path: Path) -> None:
    big = write_yaml(tmp_path / "big.yaml", "#" * (MAX_CONFIG_BYTES + 1))
    with pytest.raises(ConfigurationError, match="exceeds"):
        load_config(big)
