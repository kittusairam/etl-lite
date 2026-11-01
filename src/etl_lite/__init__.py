"""ETL Lite - a declarative, secure-by-default Extract-Transform-Load framework."""

from importlib.metadata import PackageNotFoundError, version

from etl_lite.config import JobConfig, load_config, parse_config
from etl_lite.context import RuntimeContext
from etl_lite.exceptions import (
    ConfigurationError,
    ETLError,
    ExtractionError,
    LoadError,
    SecurityError,
    TransformationError,
)
from etl_lite.pipeline import Pipeline, PipelineResult

try:
    __version__ = version("etl-lite")
except PackageNotFoundError:  # running from a source checkout without installation
    __version__ = "0.0.0+unknown"

__all__ = [
    "ConfigurationError",
    "ETLError",
    "ExtractionError",
    "JobConfig",
    "LoadError",
    "Pipeline",
    "PipelineResult",
    "RuntimeContext",
    "SecurityError",
    "TransformationError",
    "__version__",
    "load_config",
    "parse_config",
]
