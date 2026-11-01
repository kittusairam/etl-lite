# Pipeline Configuration Guide

A job is a YAML file with three main sections. Transformations run in the order they're listed.

```yaml
name: my-job                 # optional; letters, digits, . _ -  (default: etl-job)
description: Free text       # optional
source: { ... }              # where data comes from
transformations: [ ... ]     # optional, applied in order
load: { ... }                # where data goes
```

Unknown keys are rejected, and type names (`csv`, `filter`, ...) are lowercase.
`etl-lite validate --config job.yaml` checks a job without reading or writing data.

## Paths and the data root

All `path` values and SQLite database files must resolve inside the **data root**
(`--data-root` or `ETL_LITE_DATA_ROOT`, defaulting to the current directory). Relative paths are resolved
against it. Paths that escape it through `..`, absolute paths or symlinks are rejected. Remote URLs
(`s3://`, `http://`) aren't supported.

## Environment variables and secrets

String values may reference environment variables:

| Syntax | Behaviour |
|---|---|
| `${VAR}` | Value of `VAR`; the job fails if it isn't set |
| `${VAR:-default}` | Value of `VAR`, or `default` if it isn't set |
| `${ETL_LITE_ENV}` | Always set to the CLI `--env` value |

Substitution happens *after* YAML parsing, so a variable can never change the document structure.
Nested references inside a default (`${A:-${B}}`) aren't supported.
**Never hard-code passwords in job files.** Use `db_url: "${WAREHOUSE_URL}"` and inject the variable from
your secret manager.

## Sources (`source`)

### CSV

```yaml
source:
  type: csv
  path: data/input.csv
  options:            # optional; only these pandas.read_csv options are accepted:
    sep: ","          # sep, delimiter, header, names, usecols, dtype, encoding, na_values,
    encoding: utf-8   # keep_default_na, skiprows, nrows, quotechar, decimal, thousands,
                      # parse_dates, comment, skip_blank_lines
```

### Parquet

```yaml
source:
  type: parquet
  path: data/input.parquet
  columns: [id, name]   # optional: read only these columns
```

### SQLite / SQL database

```yaml
source:
  type: sqlite                          # or `sql` for any SQLAlchemy database (install its driver)
  db_url: "sqlite:///data/app.db"       # for `sql`, e.g. "${WAREHOUSE_URL}"
  table: customers                      # either `table` ...
  schema: analytics                     # optional schema for `table`
```

```yaml
source:
  type: sql
  db_url: "${WAREHOUSE_URL}"
  query: "SELECT id, email FROM customers WHERE region = :region AND created >= :since"
  params: { region: EMEA, since: "2026-01-01" }   # bound parameters; never format values into SQL
```

Rules:
- Specify exactly one of `table` or `query`.
- `query` must be one read-only `SELECT` / `WITH` statement. Write and DDL keywords
  (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ATTACH`, `PRAGMA`, ...) are rejected, even inside string literals. Pass such values via `params`.
- Table and schema names must be plain identifiers (`[A-Za-z_][A-Za-z0-9_]*`).
- `type: sqlite` requires a `sqlite:///` URL. SQLite URLs can't carry query parameters.

## Transformations (`transformations`)

| Action | Fields | Effect |
|---|---|---|
| `select` | `columns: [..]` | Keep only these columns, in this order |
| `filter` | `condition: "<expr>"` | Keep rows where the condition is true |
| `rename` | `mapping: {old: new}` | Rename columns |
| `drop` | `columns: [..]` | Remove columns |
| `deduplicate` | `subset: [..]` (optional), `keep: first\|last` | Drop duplicate rows |

Steps that name a missing column fail with a clear error.

### Filter expressions

```yaml
- action: filter
  condition: "score >= 80 and city in ['Oslo', 'Rome'] and email != None"
```

| Feature | Example |
|---|---|
| Comparisons | `age >= 18`, `status != 'closed'`, `1 < rank <= 10` |
| Membership | `country in ['NO', 'SE']`, `tier not in ('free',)` |
| Boolean logic | `a > 1 and not b == 2`, `(a > 1) & (b < 5)`, `~(x == 0)` |
| Null checks | `email == None`, `email != None` |
| Column names with spaces | `` `unit price` > 9.99 `` |

Function calls, attribute access, indexing, arithmetic and anything else are rejected when the
config is loaded. That makes filter conditions safe even when job files come from less-trusted authors.

## Targets (`load`)

### CSV

```yaml
load:
  type: csv
  path: out/result.csv
  mode: replace           # replace (default) | fail (error if the file exists)
  escape_formulas: false  # true: prefix cells starting with = + - @ with ' (spreadsheet-injection protection)
  options:                # optional: sep, encoding, na_rep, float_format, header, quotechar,
    sep: ";"              #           date_format, lineterminator
```

### Parquet

```yaml
load:
  type: parquet
  path: out/result.parquet
  mode: replace           # replace | fail
  compression: snappy     # snappy | gzip | zstd | brotli | none
```

File targets are written atomically: data goes to a temporary file in the same directory, which is then
renamed into place. Parent directories are created as needed, and new files are readable only by their owner (`0600`).

### SQLite / SQL database

```yaml
load:
  type: sqlite            # or sql
  db_url: "sqlite:///data/warehouse.db"
  table: customers
  schema: analytics       # optional
  mode: append            # append (default) | replace | fail
  chunksize: 10000        # optional batch size for large frames
```

Database loads run in one transaction, so a failure leaves the table unchanged.
There's no `upsert` mode; load into a staging table and merge in the database instead.

## Complete examples

See [config/](../config/): `to_parquet.yaml`, `from_parquet.yaml` and `csv_to_sqlite.yaml`.
