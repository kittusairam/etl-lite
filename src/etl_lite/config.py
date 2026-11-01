"""Job configuration schema and secure YAML loader.

Configurations are validated with strict Pydantic models: unknown keys are rejected, each
connector type has its own schema, and pass-through options are restricted to an allow-list.
Environment variables (``${VAR}`` or ``${VAR:-default}``) are substituted into string *values*
after YAML parsing, so a variable can never change the structure of the document.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from etl_lite.exceptions import ConfigurationError
from etl_lite.expression import FilterExpression
from etl_lite.security import parse_db_url, validate_identifier, validate_read_only_query

MAX_CONFIG_BYTES = 1_048_576

CSV_READ_OPTIONS = frozenset(
    {
        "sep",
        "delimiter",
        "header",
        "names",
        "usecols",
        "dtype",
        "encoding",
        "na_values",
        "keep_default_na",
        "skiprows",
        "nrows",
        "quotechar",
        "decimal",
        "thousands",
        "parse_dates",
        "comment",
        "skip_blank_lines",
    }
)
CSV_WRITE_OPTIONS = frozenset(
    {"sep", "encoding", "na_rep", "float_format", "header", "quotechar", "date_format", "lineterminator"}
)

_ENV_REFERENCE = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _check_options(options: dict[str, Any], allowed: frozenset[str], kind: str) -> dict[str, Any]:
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ValueError(
            f"Unsupported {kind} option(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(allowed))}."
        )
    return options


def _check_local_path(path: str) -> str:
    if "://" in path:
        raise ValueError("Remote URLs are not supported; 'path' must be a local file path.")
    return path


LocalPath = Annotated[str, Field(min_length=1, max_length=4096), AfterValidator(_check_local_path)]
ColumnList = Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]


# --------------------------------------------------------------------------- sources


class CsvSource(_StrictModel):
    type: Literal["csv"]
    path: LocalPath
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("options")
    @classmethod
    def _validate_options(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _check_options(value, CSV_READ_OPTIONS, "CSV read")


class ParquetSource(_StrictModel):
    type: Literal["parquet"]
    path: LocalPath
    columns: ColumnList | None = None


class _SqlConnection(_StrictModel):
    type: Literal["sqlite", "sql"]
    db_url: SecretStr
    db_schema: str | None = Field(default=None, alias="schema")

    @field_validator("db_schema")
    @classmethod
    def _validate_schema(cls, value: str | None) -> str | None:
        return None if value is None else validate_identifier(value, "schema name")

    @model_validator(mode="after")
    def _validate_backend(self) -> _SqlConnection:
        url = parse_db_url(self.db_url.get_secret_value())
        if self.type == "sqlite" and url.get_backend_name() != "sqlite":
            raise ValueError(
                "type 'sqlite' requires a sqlite:/// db_url; use type 'sql' for other databases."
            )
        return self


class SqlSource(_SqlConnection):
    table: str | None = None
    query: str | None = Field(default=None, max_length=100_000)
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("table")
    @classmethod
    def _validate_table(cls, value: str | None) -> str | None:
        return None if value is None else validate_identifier(value, "table name")

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str | None) -> str | None:
        return None if value is None else validate_read_only_query(value)

    @model_validator(mode="after")
    def _validate_table_or_query(self) -> SqlSource:
        if (self.table is None) == (self.query is None):
            raise ValueError("Specify exactly one of 'table' or 'query'.")
        if self.params and self.query is None:
            raise ValueError("'params' can only be used together with 'query'.")
        return self


SourceConfig = Annotated[CsvSource | ParquetSource | SqlSource, Field(discriminator="type")]


# --------------------------------------------------------------------------- transformations


class SelectStep(_StrictModel):
    action: Literal["select"]
    columns: ColumnList


class FilterStep(_StrictModel):
    action: Literal["filter"]
    condition: str

    @field_validator("condition")
    @classmethod
    def _validate_condition(cls, value: str) -> str:
        FilterExpression.parse(value)
        return value


class RenameStep(_StrictModel):
    action: Literal["rename"]
    mapping: Annotated[dict[str, Annotated[str, Field(min_length=1)]], Field(min_length=1)]


class DropStep(_StrictModel):
    action: Literal["drop"]
    columns: ColumnList


class DeduplicateStep(_StrictModel):
    action: Literal["deduplicate"]
    subset: ColumnList | None = None
    keep: Literal["first", "last"] = "first"


TransformationConfig = Annotated[
    SelectStep | FilterStep | RenameStep | DropStep | DeduplicateStep,
    Field(discriminator="action"),
]


# --------------------------------------------------------------------------- targets


class CsvTarget(_StrictModel):
    type: Literal["csv"]
    path: LocalPath
    mode: Literal["replace", "fail"] = "replace"
    escape_formulas: bool = False
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("options")
    @classmethod
    def _validate_options(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _check_options(value, CSV_WRITE_OPTIONS, "CSV write")


class ParquetTarget(_StrictModel):
    type: Literal["parquet"]
    path: LocalPath
    mode: Literal["replace", "fail"] = "replace"
    compression: Literal["snappy", "gzip", "zstd", "brotli", "none"] = "snappy"


class SqlTarget(_SqlConnection):
    table: str
    mode: Literal["append", "replace", "fail"] = "append"
    chunksize: Annotated[int, Field(gt=0, le=1_000_000)] | None = None

    @field_validator("table")
    @classmethod
    def _validate_table(cls, value: str) -> str:
        return validate_identifier(value, "table name")


TargetConfig = Annotated[CsvTarget | ParquetTarget | SqlTarget, Field(discriminator="type")]


# --------------------------------------------------------------------------- job


class JobConfig(_StrictModel):
    """A complete ETL job: one source, ordered transformations, one target."""

    name: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")] = "etl-job"
    description: str | None = None
    source: SourceConfig
    transformations: list[TransformationConfig] = Field(default_factory=list)
    load: TargetConfig

    @field_validator("transformations", mode="before")
    @classmethod
    def _none_means_empty(cls, value: Any) -> Any:
        return [] if value is None else value


# --------------------------------------------------------------------------- loading


class _NoAliasSafeLoader(yaml.SafeLoader):
    """``SafeLoader`` that rejects aliases, preventing "billion laughs" style expansion."""

    def compose_node(self, parent: yaml.Node | None, index: Any) -> yaml.Node | None:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()  # type: ignore[no-untyped-call]
            raise yaml.composer.ComposerError(
                None, None, "YAML aliases are not permitted in job configurations", event.start_mark
            )
        return super().compose_node(parent, index)


def interpolate_env_vars(value: Any, environ: Mapping[str, str]) -> Any:
    """Recursively substitute ``${VAR}`` / ``${VAR:-default}`` in string values."""
    if isinstance(value, str):

        def _replace(match: re.Match[str]) -> str:
            name, default = match.group("name"), match.group("default")
            if name in environ:
                return environ[name]
            if default is not None:
                return default
            raise ConfigurationError(f"Environment variable '{name}' is not set.")

        return _ENV_REFERENCE.sub(_replace, value)
    if isinstance(value, dict):
        return {key: interpolate_env_vars(item, environ) for key, item in value.items()}
    if isinstance(value, list):
        return [interpolate_env_vars(item, environ) for item in value]
    return value


def parse_config(data: Mapping[str, Any]) -> JobConfig:
    """Validate an already-loaded mapping into a :class:`JobConfig`."""
    try:
        return JobConfig.model_validate(data)
    except ValidationError as exc:
        # include_input=False keeps secrets (e.g. db_url) out of error messages.
        problems = "\n".join(
            f"  - {'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise ConfigurationError(f"Invalid job configuration:\n{problems}") from None


def load_config(path: str | Path, *, environ: Mapping[str, str] | None = None) -> JobConfig:
    """Load, interpolate and validate a YAML job configuration file.

    Args:
        path: Location of the YAML file.
        environ: Variables available for ``${VAR}`` substitution. Defaults to ``os.environ``.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigurationError(f"Configuration file not found: {config_path}")
    if config_path.stat().st_size > MAX_CONFIG_BYTES:
        raise ConfigurationError(f"Configuration file exceeds {MAX_CONFIG_BYTES} bytes: {config_path}")

    try:
        text = config_path.read_text(encoding="utf-8")
        # _NoAliasSafeLoader subclasses yaml.SafeLoader, so no arbitrary objects are constructed.
        raw = yaml.load(text, Loader=_NoAliasSafeLoader)  # noqa: S506  # nosec B506
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"Cannot read configuration file {config_path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {config_path}: {exc}") from None
    except RecursionError:
        raise ConfigurationError(f"Configuration file is nested too deeply: {config_path}") from None

    if not isinstance(raw, dict):
        raise ConfigurationError("Configuration root must be a YAML mapping.")

    return parse_config(interpolate_env_vars(raw, os.environ if environ is None else environ))
