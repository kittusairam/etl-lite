import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from etl_lite import __version__
from etl_lite.cli import EXIT_JOB_FAILED, app

runner = CliRunner()


@pytest.fixture
def job_file(data_root: Path) -> Path:
    config = {
        "name": "cli-job",
        "source": {"type": "csv", "path": "input.csv"},
        "transformations": [{"action": "filter", "condition": "id <= 2"}],
        "load": {"type": "csv", "path": "${OUT_NAME:-out}_${ETL_LITE_ENV}.csv"},
    }
    path = data_root / "job.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_run_succeeds(job_file: Path, data_root: Path) -> None:
    result = runner.invoke(
        app, ["run", "--config", str(job_file), "--env", "qa", "--data-root", str(data_root)]
    )
    assert result.exit_code == 0, result.output
    assert (data_root / "out_qa.csv").read_text().count("\n") == 3


def test_run_with_json_logs(job_file: Path, data_root: Path) -> None:
    result = runner.invoke(
        app,
        ["run", "-c", str(job_file), "--data-root", str(data_root), "--log-format", "json"],
    )
    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    completed = [r for r in records if "completed" in r["message"]]
    assert completed
    assert completed[0]["job"] == "cli-job"
    assert completed[0]["rows"] == 2


def test_validate_does_not_write(job_file: Path, data_root: Path) -> None:
    result = runner.invoke(app, ["validate", "-c", str(job_file), "--data-root", str(data_root)])
    assert result.exit_code == 0, result.output
    assert "is valid" in result.stderr
    assert not (data_root / "out_dev.csv").exists()


def test_job_failure_exit_code(data_root: Path) -> None:
    bad = data_root / "bad.yaml"
    bad.write_text("source:\n  type: csv\n  path: ../../etc/passwd\nload:\n  type: csv\n  path: o.csv\n")
    result = runner.invoke(app, ["run", "-c", str(bad), "--data-root", str(data_root)])
    assert result.exit_code == EXIT_JOB_FAILED
    assert "outside the permitted data root" in result.stderr


@pytest.mark.parametrize("env", ["PROD", "prod;rm -rf", "a" * 40])
def test_rejects_invalid_env(job_file: Path, env: str) -> None:
    result = runner.invoke(app, ["run", "-c", str(job_file), "--env", env])
    assert result.exit_code == 2


def test_missing_config_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "-c", str(tmp_path / "missing.yaml")])
    assert result.exit_code == 2
