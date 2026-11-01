"""Security helpers: filesystem confinement, identifier validation and secret masking."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from etl_lite.exceptions import SecurityError

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

# Statements that change data or schema. Queries are expected to be read-only.
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke"
    r"|attach|detach|pragma|vacuum|copy|call|exec|execute|load_extension)\b",
    re.IGNORECASE,
)
_READ_PREFIX = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def resolve_within(path: str | Path, root: Path) -> Path:
    """Resolve ``path`` (relative paths are taken from ``root``) and ensure it stays inside ``root``.

    Symlinks are resolved before the check, so a link pointing outside the root is rejected.
    """
    root = root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise SecurityError(f"Path '{path}' resolves outside the permitted data root '{root}'.")
    return resolved


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """Ensure ``name`` is a plain SQL identifier (letters, digits, underscore)."""
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(
            f"Invalid {kind} '{name}': use letters, digits and underscores only, "
            "starting with a letter or underscore (max 128 characters)."
        )
    return name


def validate_read_only_query(query: str) -> str:
    """Reject anything other than a single read-only ``SELECT``/``WITH`` statement.

    This is defence in depth; the database account used by a job should still be
    granted read-only privileges on its source.
    """
    statement = query.strip().rstrip(";").strip()
    if not statement:
        raise ValueError("SQL query must not be empty.")
    if ";" in statement:
        raise ValueError("SQL query must contain a single statement.")
    if not _READ_PREFIX.match(statement):
        raise ValueError("SQL query must start with SELECT or WITH.")
    if match := _WRITE_KEYWORDS.search(statement):
        raise ValueError(
            f"SQL query contains the disallowed keyword '{match.group(0)}'. "
            "Only read-only queries are permitted; pass values through 'params'."
        )
    return statement


def parse_db_url(raw_url: str) -> URL:
    """Parse a SQLAlchemy URL without echoing it back in error messages."""
    try:
        return make_url(raw_url)
    except ArgumentError:
        raise ValueError("db_url is not a valid SQLAlchemy database URL.") from None


def mask_db_url(url: URL | str) -> str:
    """Render a database URL with its password hidden, safe for logs and errors."""
    try:
        parsed = url if isinstance(url, URL) else make_url(url)
    except ArgumentError:
        return "<invalid database URL>"
    return parsed.render_as_string(hide_password=True)
