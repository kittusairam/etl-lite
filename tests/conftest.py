from pathlib import Path

import pandas as pd
import pytest

from etl_lite import RuntimeContext


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
            "score": [85, 90, 78, 92, 88],
            "city": ["Oslo", "Rome", "Oslo", None, "Lima"],
        }
    )


@pytest.fixture
def data_root(tmp_path: Path, sample_df: pd.DataFrame) -> Path:
    root = tmp_path / "data_root"
    root.mkdir()
    sample_df.to_csv(root / "input.csv", index=False)
    return root


@pytest.fixture
def context(data_root: Path) -> RuntimeContext:
    return RuntimeContext(data_root=data_root, env="test")
