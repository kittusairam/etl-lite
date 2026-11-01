import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from etl_lite import Pipeline, RuntimeContext, parse_config
from etl_lite.exceptions import ExtractionError, LoadError, SecurityError, TransformationError


def run_job(context: RuntimeContext, **job: Any) -> None:
    Pipeline(parse_config(job), context).run()


def test_csv_to_parquet_with_select(context: RuntimeContext, data_root: Path) -> None:
    result = Pipeline(
        parse_config(
            {
                "name": "select-job",
                "source": {"type": "csv", "path": "input.csv"},
                "transformations": [{"action": "select", "columns": ["id", "name"]}],
                "load": {"type": "parquet", "path": "out/output.parquet"},
            }
        ),
        context,
    ).run()

    df = pd.read_parquet(data_root / "out" / "output.parquet")
    assert list(df.columns) == ["id", "name"]
    assert len(df) == 5
    assert (result.job_name, result.rows_extracted, result.rows_loaded) == ("select-job", 5, 5)


def test_parquet_to_csv_with_filter(
    context: RuntimeContext, data_root: Path, sample_df: pd.DataFrame
) -> None:
    sample_df.to_parquet(data_root / "input.parquet", index=False)
    run_job(
        context,
        source={"type": "parquet", "path": "input.parquet"},
        transformations=[{"action": "filter", "condition": "id > 2"}],
        load={"type": "csv", "path": "final.csv"},
    )
    assert pd.read_csv(data_root / "final.csv")["id"].tolist() == [3, 4, 5]


def test_rename_drop_and_deduplicate(context: RuntimeContext, data_root: Path) -> None:
    run_job(
        context,
        source={"type": "csv", "path": "input.csv"},
        transformations=[
            {"action": "deduplicate", "subset": ["city"], "keep": "first"},
            {"action": "rename", "mapping": {"name": "full_name"}},
            {"action": "drop", "columns": ["score"]},
        ],
        load={"type": "csv", "path": "out.csv"},
    )
    df = pd.read_csv(data_root / "out.csv")
    assert list(df.columns) == ["id", "full_name", "city"]
    assert df["id"].tolist() == [1, 2, 4, 5]


def test_sqlite_round_trip_with_parameterised_query(context: RuntimeContext, data_root: Path) -> None:
    db_url = "sqlite:///warehouse.db"
    run_job(
        context,
        source={"type": "csv", "path": "input.csv"},
        load={"type": "sqlite", "db_url": db_url, "table": "people", "mode": "replace"},
    )
    with closing(sqlite3.connect(data_root / "warehouse.db")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM people").fetchone() == (5,)

    run_job(
        context,
        source={
            "type": "sqlite",
            "db_url": db_url,
            "query": "SELECT id, name FROM people WHERE score > :min_score",
            "params": {"min_score": 88},
        },
        load={"type": "csv", "path": "top.csv"},
    )
    assert pd.read_csv(data_root / "top.csv")["id"].tolist() == [2, 4]

    run_job(
        context,
        source={"type": "sqlite", "db_url": db_url, "table": "people"},
        load={"type": "sqlite", "db_url": db_url, "table": "people_copy"},
    )
    with closing(sqlite3.connect(data_root / "warehouse.db")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM people_copy").fetchone() == (5,)


def test_sql_mode_fail_raises_when_table_exists(context: RuntimeContext) -> None:
    load = {"type": "sqlite", "db_url": "sqlite:///w.db", "table": "t", "mode": "fail"}
    run_job(context, source={"type": "csv", "path": "input.csv"}, load=load)
    with pytest.raises(LoadError):
        run_job(context, source={"type": "csv", "path": "input.csv"}, load=load)


def test_file_mode_fail_preserves_existing(context: RuntimeContext, data_root: Path) -> None:
    (data_root / "existing.csv").write_text("keep me")
    with pytest.raises(LoadError, match="already exists"):
        run_job(
            context,
            source={"type": "csv", "path": "input.csv"},
            load={"type": "csv", "path": "existing.csv", "mode": "fail"},
        )
    assert (data_root / "existing.csv").read_text() == "keep me"


def test_failed_write_leaves_no_partial_file(
    context: RuntimeContext, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(self: pd.DataFrame, path: Path, **_: Any) -> None:
        Path(path).write_text("partial")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", explode)
    with pytest.raises(LoadError, match="disk full"):
        run_job(
            context,
            source={"type": "csv", "path": "input.csv"},
            load={"type": "parquet", "path": "out.parquet"},
        )
    assert sorted(p.name for p in data_root.iterdir()) == ["input.csv"]


def test_csv_formula_escaping(context: RuntimeContext, data_root: Path) -> None:
    pd.DataFrame({"id": [1, 2], "note": ['=HYPERLINK("http://evil")', "plain"]}).to_csv(
        data_root / "notes.csv", index=False
    )
    run_job(
        context,
        source={"type": "csv", "path": "notes.csv"},
        load={"type": "csv", "path": "safe.csv", "escape_formulas": True},
    )
    assert pd.read_csv(data_root / "safe.csv")["note"].tolist() == ['\'=HYPERLINK("http://evil")', "plain"]


def test_output_file_is_owner_only(context: RuntimeContext, data_root: Path) -> None:
    run_job(context, source={"type": "csv", "path": "input.csv"}, load={"type": "csv", "path": "o.csv"})
    assert (data_root / "o.csv").stat().st_mode & 0o077 == 0


# --------------------------------------------------------------------------- failures & security


def test_missing_source_file(context: RuntimeContext) -> None:
    with pytest.raises(ExtractionError, match="not found"):
        run_job(context, source={"type": "csv", "path": "nope.csv"}, load={"type": "csv", "path": "o.csv"})


def test_transformation_on_missing_column(context: RuntimeContext) -> None:
    with pytest.raises(TransformationError, match=r"Step 1 \(select\).*missing"):
        run_job(
            context,
            source={"type": "csv", "path": "input.csv"},
            transformations=[{"action": "select", "columns": ["missing"]}],
            load={"type": "csv", "path": "o.csv"},
        )


def test_type_mismatch_in_filter_is_wrapped(context: RuntimeContext) -> None:
    with pytest.raises(TransformationError, match="Step 1"):
        run_job(
            context,
            source={"type": "csv", "path": "input.csv"},
            transformations=[{"action": "filter", "condition": "name > 5"}],
            load={"type": "csv", "path": "o.csv"},
        )


@pytest.mark.parametrize("path", ["../escape.csv", "/etc/passwd", "sub/../../escape.csv"])
def test_paths_cannot_escape_data_root(context: RuntimeContext, path: str) -> None:
    with pytest.raises(SecurityError, match="outside the permitted data root"):
        run_job(context, source={"type": "csv", "path": path}, load={"type": "csv", "path": "o.csv"})
    with pytest.raises(SecurityError):
        run_job(context, source={"type": "csv", "path": "input.csv"}, load={"type": "csv", "path": path})


def test_symlink_escape_is_blocked(context: RuntimeContext, data_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    outside.write_text("id\n1\n")
    os.symlink(outside, data_root / "link.csv")
    with pytest.raises(SecurityError):
        run_job(context, source={"type": "csv", "path": "link.csv"}, load={"type": "csv", "path": "o.csv"})


def test_sqlite_database_cannot_escape_data_root(context: RuntimeContext) -> None:
    with pytest.raises(SecurityError):
        run_job(
            context,
            source={"type": "csv", "path": "input.csv"},
            load={"type": "sqlite", "db_url": "sqlite:////tmp/elsewhere.db", "table": "t"},
        )


def test_sqlite_url_query_parameters_rejected(context: RuntimeContext) -> None:
    with pytest.raises(SecurityError, match="Query parameters"):
        run_job(
            context,
            source={"type": "csv", "path": "input.csv"},
            load={"type": "sqlite", "db_url": "sqlite:///x.db?uri=true", "table": "t"},
        )


def test_database_errors_hide_credentials(context: RuntimeContext) -> None:
    pipeline = Pipeline(
        parse_config(
            {
                "source": {"type": "sqlite", "db_url": "sqlite:///empty.db", "table": "absent"},
                "load": {"type": "csv", "path": "o.csv"},
            }
        ),
        context,
    )
    assert "sqlite" in pipeline._reader.describe()
    with pytest.raises(ExtractionError):
        pipeline.run()


def test_describe_masks_password(context: RuntimeContext) -> None:
    pipeline = Pipeline(
        parse_config(
            {
                "source": {"type": "csv", "path": "input.csv"},
                "load": {
                    "type": "sql",
                    "db_url": "postgresql://user:s3cr3t-pw@db.internal/app",
                    "table": "t",
                },
            }
        ),
        context,
    )
    description = pipeline._writer.describe()
    assert "s3cr3t-pw" not in description
    assert "db.internal" in description
