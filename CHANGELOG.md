# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-01

### Breaking changes
- The package moved from `src.etl` to `etl_lite`. Import from `etl_lite` and use `etl_lite.cli:app` as the entry point.
- The CLI now has subcommands: `etl-lite run --config ...` (previously `etl-lite --config ...`).
- `ETLEngine` is replaced by `Pipeline`, which returns a `PipelineResult`.
- Job configs are strict: unknown keys are rejected and type names must be lowercase.
- Env-var interpolation supports only `${VAR}` / `${VAR:-default}`; bare `$VAR` is no longer substituted.
- File targets accept `mode: replace | fail`. The previously documented but unimplemented `upsert` mode is removed.

### Added
- `validate` command, `--version`, `--data-root`, `--log-level`, `--log-format json`, and env-var equivalents.
- Transformations: `rename`, `drop`, `deduplicate`. Filter conditions support `in`, `not in`, null checks and backtick-quoted column names.
- `type: sql` for any SQLAlchemy database. Parameterised source queries via `params`. Target `schema` and `chunksize`.
- Parquet `columns` (source) and `compression` (target). CSV `escape_formulas`.
- Connector and transformation registries for extension.
- Tooling: ruff, mypy `--strict`, bandit, coverage gate, pre-commit and GitHub Actions CI. `SECURITY.md`.

### Security
- Filter conditions no longer use `DataFrame.query`, closing a code-execution path.
- Env vars are interpolated after YAML parsing, so variables can't inject YAML.
- Paths and SQLite databases are confined to the data root. Remote URLs are rejected.
- Source SQL must be read-only. Table and schema names are validated.
- Credentials are masked in logs and errors. Typer local-variable tracebacks are disabled.
- YAML aliases and oversized configs are rejected. pandas pass-through options are allow-listed.
- Outputs are written atomically with owner-only permissions. Database loads are transactional.

### Fixed
- `NameError` (`ETLError` not imported) that hid every configuration error.
- SQLAlchemy engines are now disposed after use.
- The `--env` option now takes effect: it's validated, logged and exposed as `${ETL_LITE_ENV}`.

### Removed
- Unused `openpyxl` dependency.
