import pandas as pd
import pytest

from etl_lite.exceptions import TransformationError
from etl_lite.expression import FilterExpression


def ids(df: pd.DataFrame, condition: str) -> list[int]:
    return df.loc[FilterExpression.parse(condition).evaluate(df), "id"].tolist()


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("id < 4", [1, 2, 3]),
        ("score >= 88 and id != 2", [4, 5]),
        ("score > 90 or name == 'Alice'", [1, 4]),
        ("(score > 85) & (id < 3)", [2]),
        ("~(id > 1)", [1]),
        ("not id > 1", [1]),
        ("2 <= id < 4", [2, 3]),
        ("city in ['Oslo', 'Lima']", [1, 3, 5]),
        ("city not in ('Oslo',)", [2, 4, 5]),
        ("city == None", [4]),
        ("city != None", [1, 2, 3, 5]),
        ("score > -1", [1, 2, 3, 4, 5]),
        ("True", [1, 2, 3, 4, 5]),
    ],
)
def test_supported_expressions(sample_df: pd.DataFrame, condition: str, expected: list[int]) -> None:
    assert ids(sample_df, condition) == expected


def test_backtick_column_names() -> None:
    df = pd.DataFrame({"id": [1, 2], "unit price": [5, 15]})
    assert ids(df, "`unit price` > 10") == [2]


@pytest.mark.parametrize(
    "malicious",
    [
        "__import__('os').system('echo pwned')",
        "@pd.io.common.os.system('id')",
        "id.__class__.__bases__",
        "name.str.contains('A')",
        "id[0] == 1",
        "id + 1 > 2",
        "(lambda: 1)()",
        "[x for x in id]",
        "open('/etc/passwd')",
        "id == b'1'",
        "id in [score]",
    ],
)
def test_rejects_code_execution_and_unsupported_syntax(malicious: str) -> None:
    with pytest.raises(ValueError, match=r"(?i)unsupported|invalid|literal"):
        FilterExpression.parse(malicious)


@pytest.mark.parametrize("bad", ["", "   ", "x" * 2001, " or ".join(["id == 1"] * 100)])
def test_rejects_empty_or_oversized(bad: str) -> None:
    with pytest.raises(ValueError, match=r"empty|exceeds|too complex"):
        FilterExpression.parse(bad)


def test_unknown_column(sample_df: pd.DataFrame) -> None:
    with pytest.raises(TransformationError, match="Unknown column 'missing'"):
        FilterExpression.parse("missing > 1").evaluate(sample_df)


def test_non_boolean_result(sample_df: pd.DataFrame) -> None:
    with pytest.raises(TransformationError, match="true/false"):
        FilterExpression.parse("id").evaluate(sample_df)


@pytest.mark.parametrize("condition", ["1 < 2", "1 in [1]", "None == None"])
def test_comparisons_must_reference_columns(sample_df: pd.DataFrame, condition: str) -> None:
    with pytest.raises(TransformationError):
        FilterExpression.parse(condition).evaluate(sample_df)
