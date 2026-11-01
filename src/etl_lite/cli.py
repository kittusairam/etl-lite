"""Command-line interface (``etl-lite``)."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from etl_lite import __version__
from etl_lite.config import load_config
from etl_lite.context import RuntimeContext
from etl_lite.exceptions import ETLError
from etl_lite.log import LogFormat, LogLevel, configure_logging
from etl_lite.pipeline import Pipeline

EXIT_JOB_FAILED = 1
EXIT_INTERNAL_ERROR = 3

_ENV_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

logger = logging.getLogger("etl_lite.cli")

# Pretty exceptions are disabled: Typer's default renderer prints local variables, which can
# include credentials, to the terminal on an unhandled error.
app = typer.Typer(
    help="ETL Lite - declarative, secure-by-default Extract-Transform-Load jobs.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _validate_env(value: str) -> str:
    if not _ENV_NAME.fullmatch(value):
        raise typer.BadParameter("must be lowercase letters, digits, '-' or '_' (max 32 chars)")
    return value


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


ConfigOption = Annotated[
    Path,
    typer.Option(
        "--config",
        "-c",
        help="Path to the YAML job configuration.",
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
]
EnvOption = Annotated[
    str,
    typer.Option(
        "--env",
        "-e",
        envvar="ETL_LITE_ENV",
        callback=_validate_env,
        help="Deployment environment label; available in configs as ${ETL_LITE_ENV}.",
    ),
]
DataRootOption = Annotated[
    Path | None,
    typer.Option(
        "--data-root",
        envvar="ETL_LITE_DATA_ROOT",
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Directory all data files must live under. Defaults to the current directory.",
    ),
]
LogLevelOption = Annotated[
    LogLevel, typer.Option("--log-level", envvar="ETL_LITE_LOG_LEVEL", case_sensitive=False)
]
LogFormatOption = Annotated[
    LogFormat, typer.Option("--log-format", envvar="ETL_LITE_LOG_FORMAT", case_sensitive=False)
]


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """ETL Lite - declarative, secure-by-default Extract-Transform-Load jobs."""


@contextmanager
def _exit_on_error() -> Iterator[None]:
    try:
        yield
    except ETLError as exc:
        logger.error("%s", exc)
        raise typer.Exit(EXIT_JOB_FAILED) from None
    except Exception:
        logger.error("Unexpected internal error; re-run with --log-level DEBUG for the traceback.")
        logger.debug("Traceback:", exc_info=True)
        raise typer.Exit(EXIT_INTERNAL_ERROR) from None


def _build_pipeline(config: Path, env: str, data_root: Path | None) -> Pipeline:
    job = load_config(config, environ={**os.environ, "ETL_LITE_ENV": env})
    context = RuntimeContext(data_root=data_root or Path.cwd(), env=env)
    return Pipeline(job, context)


@app.command()
def run(
    config: ConfigOption,
    env: EnvOption = "dev",
    data_root: DataRootOption = None,
    log_level: LogLevelOption = LogLevel.INFO,
    log_format: LogFormatOption = LogFormat.TEXT,
) -> None:
    """Run the ETL job defined in a YAML configuration file."""
    configure_logging(log_level, log_format)
    with _exit_on_error():
        _build_pipeline(config, env, data_root).run()


@app.command()
def validate(
    config: ConfigOption,
    env: EnvOption = "dev",
    data_root: DataRootOption = None,
    log_level: LogLevelOption = LogLevel.INFO,
    log_format: LogFormatOption = LogFormat.TEXT,
) -> None:
    """Validate a job configuration and its security policies without moving any data."""
    configure_logging(log_level, log_format)
    with _exit_on_error():
        pipeline = _build_pipeline(config, env, data_root)
        logger.info("Configuration for job '%s' is valid.", pipeline.config.name)
