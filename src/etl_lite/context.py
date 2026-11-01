"""Runtime settings shared by every component of a pipeline run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RuntimeContext:
    """Execution settings that come from the caller rather than the job configuration.

    Attributes:
        data_root: Directory that all file paths and SQLite databases must live under.
            Relative paths in a job configuration are resolved against it.
        env: Deployment environment label (e.g. ``dev``, ``prod``) used for logging
            and exposed to configs as ``${ETL_LITE_ENV}``.
    """

    data_root: Path = field(default_factory=Path.cwd)
    env: str = "dev"

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_root", Path(self.data_root).resolve())
