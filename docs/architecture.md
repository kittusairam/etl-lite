# Architecture

ETL Lite turns a declarative YAML job into a validated, typed object graph. It runs that graph
through a small pipeline of pluggable readers, transformation handlers and writers.

## Design principles

1. **Validate early, fail fast.** Config errors, unsafe paths and unsafe SQL are rejected before any data
   is read. `etl-lite validate` runs every check without moving data.
2. **Secure by default.** Safety doesn't depend on job authors doing the right thing (see [SECURITY.md](../SECURITY.md)).
3. **Open for extension, closed for modification.** New connectors and transformations are added by
   registering a class or function. The pipeline itself doesn't change.
4. **Library first.** The CLI is a thin layer over a public Python API (`Pipeline`, `load_config`, `RuntimeContext`).
5. **Typed and observable.** The code passes `mypy --strict`. Logs can be emitted as structured JSON with job, env and row counts.

## Component overview

```text
            YAML file
                │
                ▼
┌───────────────────────────────┐
│ config.load_config            │  safe YAML (no tags, no aliases, size-limited)
│   ├─ env interpolation        │  ${VAR} / ${VAR:-default} into string values only
│   └─ JobConfig (Pydantic)     │  discriminated unions, extra="forbid", SecretStr
└───────────────┬───────────────┘
                │ JobConfig + RuntimeContext(data_root, env)
                ▼
┌───────────────────────────────┐
│ pipeline.Pipeline             │
│   __init__: build connectors  │──► security.resolve_within / SQLite URL confinement
│   run():                      │
│     extract ──► Reader.read   │──► connectors/{files,sql}.py
│     transform ► handlers      │──► transforms/__init__.py ──► expression.FilterExpression
│     load ─────► Writer.write  │──► atomic file write / transactional SQL write
└───────────────┬───────────────┘
                ▼
          PipelineResult (rows, duration)
```

## Modules

| Module | Responsibility |
|---|---|
| `cli.py` | Typer commands `run` and `validate`, option and env-var handling, logging setup, mapping exceptions to exit codes. Typer's pretty tracebacks are disabled so local variables (which may hold secrets) are never printed. |
| `config.py` | Pydantic models for every source, target and transformation; YAML loading; env-var interpolation; formatting validation errors without echoing input values. |
| `pipeline.py` | `Pipeline` orchestrates the three stages, wraps unexpected errors in stage-specific exceptions and returns a `PipelineResult`. |
| `connectors/` | `Reader` / `Writer` protocols (`base.py`), the type-to-class registry (`__init__.py`), and the CSV, Parquet (`files.py`) and SQL (`sql.py`) implementations. |
| `transforms/` | One handler per transformation step and a registry that applies steps in order. |
| `expression.py` | Parses filter conditions with `ast`, checks them against a node whitelist, and evaluates them on a DataFrame without `eval`. |
| `security.py` | Data-root path confinement, SQL identifier and read-only query validation, URL masking. |
| `context.py` | `RuntimeContext`, the caller-supplied settings (data root, environment) kept separate from the job definition. |
| `log.py` | Text and JSON log formatters. |
| `exceptions.py` | `ETLError` → `ConfigurationError`, `SecurityError`, `ExtractionError`, `TransformationError`, `LoadError`. |

## Error model

Every expected failure raises a subclass of `ETLError` with a message safe to show to operators.
Unexpected exceptions inside a stage are wrapped in that stage's error type, keeping the original
exception as `__cause__` for debugging. The CLI maps `ETLError` to exit code 1 and anything else to 3.

## Extending

### Add a connector (example: JSON Lines)

1. In `config.py`, add `JsonlSource(_StrictModel)` with `type: Literal["jsonl"]` and add it to the `SourceConfig` union.
2. In `connectors/files.py`, implement a class with `describe()` and `read()`. Resolve paths with `resolve_within`.
3. Register it in `connectors/__init__.py`: `_READERS[JsonlSource] = JsonlReader`.
4. Add tests, including a path-escape test.

### Add a transformation (example: `cast`)

1. In `config.py`, add `CastStep(_StrictModel)` with `action: Literal["cast"]` and add it to `TransformationConfig`.
2. In `transforms/__init__.py`, write `_cast(df, step)` and add it to `_HANDLERS`.
3. Add tests.

The pipeline, CLI and loader need no changes.

## Key decisions

| Decision | Rationale |
|---|---|
| Custom expression evaluator instead of `DataFrame.query` | `query` / `eval` can run arbitrary Python from a config file. An AST whitelist removes that risk while keeping the familiar syntax. |
| Interpolate env vars after YAML parsing | Substituting into raw text lets a variable's value inject YAML structure. Interpolating parsed string values can't. |
| Discriminated unions per connector | Each connector only accepts its own fields, so typos and unsupported options fail validation. |
| `RuntimeContext` separate from `JobConfig` | Job files are portable across environments. The operator controls the data root and environment. |
| Atomic temp-file-and-rename writes | A crash or error never leaves a half-written output for downstream consumers. |
| Absolute imports and a `src/` layout | Tests run against the installed package, which avoids import-path surprises. |
