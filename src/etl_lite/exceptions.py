"""Exception hierarchy for ETL Lite.

Every error raised deliberately by the framework derives from :class:`ETLError`,
so callers can distinguish expected job failures from programming errors.
"""


class ETLError(Exception):
    """Base class for all ETL Lite errors."""


class ConfigurationError(ETLError):
    """The job configuration is missing, malformed or fails validation."""


class SecurityError(ETLError):
    """A configuration value violates a security policy (e.g. path escapes the data root)."""


class ExtractionError(ETLError):
    """Reading data from the source failed."""


class TransformationError(ETLError):
    """Applying a transformation step failed."""


class LoadError(ETLError):
    """Writing data to the target failed."""
