# Security

## Reporting a vulnerability

Please don't open a public issue. Report suspected vulnerabilities privately to the maintainers
through your organisation's security channel, with steps to reproduce and the affected version.
Expect an acknowledgement within 3 working days.

## Threat model

| Asset | Threat | Control |
|---|---|---|
| Host running jobs | A job file executes code | YAML loaded with a `SafeLoader` subclass (no Python tags). Filter conditions are evaluated by an AST whitelist, never `eval` / `DataFrame.query` |
| Host filesystem | A job file reads or overwrites files outside its area | Every path and SQLite database is resolved (following symlinks) and must stay inside the data root. Remote URLs are rejected |
| Databases | Destructive or injected SQL | Source queries must be one read-only `SELECT`/`WITH` statement. Values are passed as bound `params`. Table and schema names must be plain identifiers |
| Credentials | Leaking in logs, errors, tracebacks or `repr` | `db_url` is a Pydantic `SecretStr`. URLs are logged with the password masked. Validation errors exclude input values. SQLAlchemy runs with `hide_parameters=True`. Typer's local-variable tracebacks are disabled |
| Config integrity | Env-var values injecting YAML structure | Variables are substituted into parsed string values, not raw text |
| Availability | Resource-exhaustion configs | 1 MiB config limit, YAML aliases rejected ("billion laughs"), length and node limits on expressions |
| Pass-through options | Abusing pandas options (e.g. `engine`, `storage_options`) | CSV read/write options are allow-listed, and unknown keys anywhere in a job are rejected |
| Output consumers | Partial files, spreadsheet formula injection | Atomic writes with owner-only permissions. Optional `escape_formulas` for CSV |

## Operator responsibilities

- **Least privilege:** give jobs a database account with only the rights they need (read-only on sources).
  The read-only query check is defence in depth, not a replacement for database permissions.
- **Secrets:** inject `db_url` and other secrets through environment variables from a secret manager.
  Never commit them to job files.
- **Data root:** point `--data-root` at a dedicated directory, not `/` or a home directory.
- **Job files:** treat job files as code. Review them and keep them under version control.
- **Dependencies:** CI runs `pip-audit` and `bandit`. Keep `poetry.lock` up to date.
- **Log handling:** logs contain file paths, table names and row counts, never row data or passwords.
  Route JSON logs to your central logging platform.
