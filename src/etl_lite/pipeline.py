"""Pipeline orchestration: extract, transform, load."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from etl_lite.config import JobConfig
from etl_lite.connectors import build_reader, build_writer
from etl_lite.context import RuntimeContext
from etl_lite.exceptions import ETLError, ExtractionError, LoadError
from etl_lite.transforms import apply_transformations

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class PipelineResult:
    """Summary of a successful pipeline run."""

    job_name: str
    rows_extracted: int
    rows_loaded: int
    duration_seconds: float


class Pipeline:
    """Runs one :class:`JobConfig`.

    Connectors are built (and every path / URL security check performed) in the constructor,
    so an invalid or unsafe job fails before any data is read or written.
    """

    def __init__(self, config: JobConfig, context: RuntimeContext | None = None) -> None:
        self.config = config
        self.context = context or RuntimeContext()
        self._reader = build_reader(config.source, self.context)
        self._writer = build_writer(config.load, self.context)

    def run(self) -> PipelineResult:
        job = self.config.name
        log_context = {"job": job, "env": self.context.env}
        started = time.perf_counter()
        logger.info("Job '%s' started (env=%s)", job, self.context.env, extra=log_context)

        logger.info("Extracting from %s", self._reader.describe(), extra=log_context)
        df = _run_stage(self._reader.read, ExtractionError, "Extraction")
        rows_extracted = len(df)
        logger.info("Extracted %d rows", rows_extracted, extra={**log_context, "rows": rows_extracted})

        df = apply_transformations(df, self.config.transformations)
        logger.info(
            "Applied %d transformation(s); %d rows remain",
            len(self.config.transformations),
            len(df),
            extra={**log_context, "rows": len(df)},
        )

        logger.info("Loading into %s", self._writer.describe(), extra=log_context)
        _run_stage(lambda: self._writer.write(df), LoadError, "Load")

        result = PipelineResult(
            job_name=job,
            rows_extracted=rows_extracted,
            rows_loaded=len(df),
            duration_seconds=round(time.perf_counter() - started, 3),
        )
        logger.info(
            "Job '%s' completed: %d rows loaded in %.3fs",
            job,
            result.rows_loaded,
            result.duration_seconds,
            extra={**log_context, "rows": result.rows_loaded, "duration_seconds": result.duration_seconds},
        )
        return result


def _run_stage(func: Callable[[], T], error_type: type[ETLError], stage: str) -> T:
    try:
        return func()
    except ETLError:
        raise
    except Exception as exc:
        raise error_type(f"{stage} failed: {type(exc).__name__}: {exc}") from exc
