"""Logging configuration (human-readable text or JSON lines for log aggregators)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from enum import StrEnum

_PACKAGE_LOGGER = "etl_lite"
_RESERVED_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class LogFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class JsonFormatter(logging.Formatter):
    """Formats each record as a single JSON object, including any ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            (key, value)
            for key, value in record.__dict__.items()
            if key not in _RESERVED_ATTRS and not key.startswith("_")
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: LogLevel = LogLevel.INFO, fmt: LogFormat = LogFormat.TEXT) -> None:
    """Send ``etl_lite`` logs to stderr. Library users may skip this and configure logging themselves."""
    handler = logging.StreamHandler(sys.stderr)
    if fmt is LogFormat.JSON:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S%z")
        )
    logger = logging.getLogger(_PACKAGE_LOGGER)
    logger.handlers[:] = [handler]
    logger.setLevel(level.value)
    logger.propagate = False
