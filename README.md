# ETL Lite

A lightweight, declarative, **secure-by-default** Extract-Transform-Load framework for Python.
You describe a job in YAML (source, transformations, target), and ETL Lite validates it and runs it.
It's built on Pandas, SQLAlchemy, Pydantic and Typer.

## Features

- **Declarative YAML jobs**: strict schemas reject unknown keys and typos before any data is touched.
- **Connectors**: CSV, Parquet, SQLite and any SQLAlchemy-supported database (`type: sql`).
- **Transformations**: `select`, `filter`, `rename`, `drop`, `deduplicate`, applied in order.
- **Safe filter expressions**: pandas-style conditions (`score > 80 and city in ['Oslo']`) evaluated without `eval`.
- **Secure by default**: paths are confined to a data root, SQL is read-only and parameterised,
  credentials are masked, and file writes are atomic. See [SECURITY.md](SECURITY.md).
- **Operations-ready CLI**: `run` and `validate` commands, JSON logs, environment-variable configuration
  and meaningful exit codes.
- **Quality gates**: full type hints (mypy `--strict`), ruff, bandit, and 98 tests at 94% coverage.

## Quick start

Requires Python 3.11+ and [Poetry](https://python-poetry.org/) 2.x.

```bash
poetry install
poetry run etl-lite validate --config config/to_parquet.yaml   # check config and security rules only
poetry run etl-lite run --config config/to_parquet.yaml        # CSV -> Parquet
poetry run etl-lite run --config config/from_parquet.yaml      # Parquet -> filtered CSV
poetry run etl-lite run --config config/csv_to_sqlite.yaml     # CSV -> cleaned SQLite table
```

### PostgreSQL

```bash
poetry install --extras postgres                                # installs the psycopg driver
export POSTGRES_URL='postgresql+psycopg://postgres:<password>@localhost:5432/postgres'
poetry run etl-lite run --config config/csv_to_postgres.yaml    # CSV -> public.customers
poetry run etl-lite run --config config/postgres_to_parquet.yaml  # Postgres -> Parquet
```

## CLI

```text
etl-lite run      --config FILE [--env NAME] [--data-root DIR] [--log-level LEVEL] [--log-format text|json]
etl-lite validate --config FILE [--env NAME] [--data-root DIR]
etl-lite --version
```

| Option | Environment variable | Default | Purpose |
|---|---|---|---|
| `--config`, `-c` | | required | YAML job file |
| `--env`, `-e` | `ETL_LITE_ENV` | `dev` | Environment label used in logs and available in configs as `${ETL_LITE_ENV}` |
| `--data-root` | `ETL_LITE_DATA_ROOT` | current directory | All data files and SQLite databases must live under this directory |
| `--log-level` | `ETL_LITE_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--log-format` | `ETL_LITE_LOG_FORMAT` | `text` | `json` emits one JSON object per line for log aggregators |

Logs go to stderr. Exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Job failed: invalid config, security violation, or an extract, transform or load error |
| `2` | Invalid command-line usage |
| `3` | Unexpected internal error (re-run with `--log-level DEBUG` for the traceback) |

## Example job

```yaml
name: customers-to-sqlite

source:
  type: csv
  path: data/source.csv

transformations:
  - action: deduplicate
    subset: [email]
  - action: filter
    condition: "id < 100 and email != None"
  - action: rename
    mapping: { name: full_name }

load:
  type: sqlite
  db_url: "${CUSTOMERS_DB_URL:-sqlite:///data/customers.db}"
  table: customers
  mode: replace
```

The full configuration reference is in [docs/pipeline-design.md](docs/pipeline-design.md).

## Using it as a library

```python
from pathlib import Path
from etl_lite import Pipeline, RuntimeContext, load_config, ETLError

try:
    result = Pipeline(
        load_config("config/to_parquet.yaml"), RuntimeContext(data_root=Path("."), env="prod")
    ).run()
    print(result.rows_loaded, result.duration_seconds)
except ETLError as exc:
    ...
```

## Project layout

```text
src/etl_lite/
├── cli.py              Typer CLI (run, validate)
├── config.py           Pydantic job schema, secure YAML loader, env-var interpolation
├── pipeline.py         Orchestrates extract -> transform -> load
├── expression.py       Safe filter-expression parser and evaluator
├── security.py         Path confinement, SQL/identifier validation, secret masking
├── context.py          RuntimeContext (data root, environment)
├── log.py              Text / JSON logging setup
├── exceptions.py       ETLError hierarchy
├── connectors/         Reader/Writer protocol + CSV, Parquet, SQL implementations
└── transforms/         Transformation step handlers
config/                 Example jobs
docs/                   Architecture and configuration guide
tests/                  Unit, integration, CLI and security tests
```

## Development

```bash
poetry install
poetry run pytest                     # tests + coverage (fails under 85%)
poetry run ruff check . && poetry run ruff format --check .
poetry run mypy                       # strict type checking
poetry run bandit -r src -c pyproject.toml
pipx run pip-audit                    # dependency vulnerability scan
pre-commit install                    # optional: run the checks on every commit
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs all of these on Python 3.11 to 3.13.

## Documentation

- [Architecture](docs/architecture.md)
- [Pipeline configuration guide](docs/pipeline-design.md)
- [Security policy and controls](SECURITY.md)
- [Changelog](CHANGELOG.md)
