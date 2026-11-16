"""
The Snowflake recipes in docs/snowflake.md run, and say what the code does.

Nothing here needs Snowflake. The handlers are lifted out of the SQL in the doc and run
against stand-ins for the two things the runtime supplies: the `_snowflake.vectorized`
decorator and the session. What is checked is the contract a pipeline is written
against: the wheel the doc names is the one this version builds, and the columns a UDTF
returns are the ones its RETURNS TABLE clause declares, in order and of that type.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import qikit

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "snowflake.md").read_text()

# What RETURNS TABLE may declare for each schema() dtype. "any" is the caller's own type.
SQL_TYPES = {"float": {"FLOAT", "DOUBLE"}, "int": {"INT", "INTEGER", "NUMBER"},
             "bool": {"BOOLEAN"}, "string": {"STRING", "VARCHAR", "TEXT"}}


def _sql_blocks() -> list[str]:
    return re.findall(r"```sql\n(.*?)```", DOC, flags=re.S)


def _block(creating: str) -> str:
    found = [b for b in _sql_blocks() if f"CREATE OR REPLACE {creating}" in b and "$$" in b]
    assert len(found) == 1, f"expected one {creating} with a body in docs/snowflake.md"
    return found[0]


def _handler(block: str, monkeypatch) -> object:
    """The object the block's HANDLER names, from its $$ body."""
    fake = types.ModuleType("_snowflake")
    fake.vectorized = lambda input: (lambda fn: fn)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_snowflake", fake)
    body = re.search(r"\$\$\n(.*?)\$\$", block, flags=re.S).group(1)  # type: ignore[union-attr]
    name = re.search(r"HANDLER = '(\w+)'", block).group(1)  # type: ignore[union-attr]
    namespace: dict[str, object] = {}
    exec(compile(body, "docs/snowflake.md", "exec"), namespace)
    return namespace[name]


def _monthly(n: int = 24) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    den = rng.integers(80, 120, n).astype(float)
    return pd.DataFrame({"MONTH": pd.date_range("2024-01-01", periods=n, freq="MS").date,
                         "NUM": rng.binomial(den.astype(int), 0.2).astype(float), "DEN": den})


def test_the_wheel_the_doc_names_is_this_version():
    """IMPORTS needs the exact file name, so a stale one installs an old release."""
    versions = set(re.findall(r"clinical_qikit-([\w.]+)-py3-none-any\.whl", DOC))
    assert versions == {qikit.__version__}, (
        f"docs/snowflake.md names the wheel for {sorted(versions)}; "
        f"this is {qikit.__version__}. Update the file names in the doc.")


def test_the_udtf_returns_the_table_it_declares(monkeypatch):
    block = _block("FUNCTION")
    declared = re.search(r"RETURNS TABLE \((.*?)\)\s*LANGUAGE", block, flags=re.S).group(1)  # type: ignore[union-attr]
    columns = [tuple(part.split()) for part in declared.replace("\n", " ").split(",")]
    arguments = re.search(r"FUNCTION [\w.]+\((.*?)\)", block).group(1)  # type: ignore[union-attr]

    df = _monthly()
    assert len(arguments.split(",")) == df.shape[1]
    df.columns = range(df.shape[1])              # Snowflake passes the columns by position
    out = _handler(block, monkeypatch)().end_partition(df)  # type: ignore[operator]

    assert len(out) == 24 and out.shape[1] == len(columns)
    dtypes = qikit.schema("qic").set_index("column")["dtype"]
    for (sql_name, sql_type), name in zip(columns, out.columns):
        if dtypes[name] == "any":                # x: the caller's column, under its own name
            assert sql_name == arguments.split(",")[0].split()[0]
            continue
        assert sql_name == name.upper()
        assert sql_type in SQL_TYPES[dtypes[name]], f"{sql_name} {sql_type} is {dtypes[name]}"
    assert set(out["signal"]) <= {"none", "outlier"}
    assert out["cl"].notna().all()


def test_the_udtf_schema_does_not_depend_on_the_options(monkeypatch):
    """to_table() is what keeps RETURNS TABLE true: the same columns whatever the call."""
    plain = qikit.qic(_monthly(), x="MONTH", y="NUM", n="DEN", chart="p").to_table()
    full = qikit.qic(_monthly().assign(P=["a"] * 12 + ["b"] * 12), x="MONTH", y="NUM",
                     n="DEN", chart="p", part="P", target=0.2).to_table()
    assert list(plain.columns) == list(full.columns) == list(qikit.schema("qic")["column"])
    assert list(plain.dtypes) == list(full.dtypes)


def test_the_stored_procedure_writes_upper_case_limits(monkeypatch):
    source = pd.concat([_monthly().assign(MEASURE=m, SERVICE=s)
                        for m in ("falls", "hai") for s in ("med", "surg")])
    written: dict[str, object] = {}

    class Session:
        def table(self, name):
            return types.SimpleNamespace(to_pandas=lambda: source.copy())

        def write_pandas(self, df, name, **options):
            written.update(df=df, name=name, options=options)

    run = _handler(_block("PROCEDURE"), monkeypatch)
    message = run(Session(), "QI.METRICS.MONTHLY", "QI.METRICS.MONTHLY_LIMITS")  # type: ignore[operator]

    out = written["df"]
    assert isinstance(out, pd.DataFrame)
    assert message == "96 rows written to QI.METRICS.MONTHLY_LIMITS"
    assert list(out.columns[:2]) == ["MEASURE", "SERVICE"]          # the facets lead
    assert all(c == c.upper() for c in out.columns)
    assert {"X", "Y", "CL", "UCL", "LCL", "SIGNAL"} <= set(out.columns)
    assert out.groupby(["MEASURE", "SERVICE"]).size().eq(24).all()


@pytest.mark.parametrize("function", ["qic", "funnel"])
def test_schema_types_all_have_a_sql_type(function):
    assert set(qikit.schema(function)["dtype"]) <= set(SQL_TYPES) | {"any"}
