"""
The docs agents read name only arguments, values, summary keys and columns that exist.

README, AGENTS.md, llms.txt, the skills and the methods docs repeat the public vocabulary.
A stale name in any of them is the likeliest way an agent writes a call that fails, or
reads a column that is not there. These tests extract every name the docs use and check
it against the code, in both directions for the documented column lists.

CHANGELOG.md is left out on purpose: it names the old arguments to say they are gone.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qikit import (
    analyze, bchart, design, funnel, funnel_rollup, funnel_sensitivity, paretochart, qic,
)
from qikit.core.dispersion import TAU_METHODS
from qikit.core.rules import METHODS
from qikit.core.shewhart import CHARTS
from qikit.funnel import MEASURES, SIGNALS
from qikit.plot.charts import _CATERPILLAR_OPTIONS, _FUNNEL_OPTIONS, _SPC_OPTIONS
from qikit.plot.options import LABEL_SIGNALS

ROOT = Path(__file__).resolve().parent.parent
DOCS = sorted(
    [ROOT / "README.md", ROOT / "llms.txt", ROOT / "src/qikit/AGENTS.md",
     ROOT / "data/examples/README.md", *ROOT.glob("docs/*.md"), *ROOT.glob("skills/*/SKILL.md")]
)
DOCS = [p for p in DOCS if "archive" not in p.parts and p.name != "excel-addin-roadmap.md"]


def _params(fn) -> set[str]:
    return {p.name for p in inspect.signature(fn).parameters.values()
            if p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)} - {"self", "removed"}


QIC = _params(qic)
FUNNEL = _params(funnel)
SENSITIVITY = _params(funnel_sensitivity) | FUNNEL
ROLLUP = _params(funnel_rollup) | FUNNEL - {"unit"}
MIN_DENOMINATOR = {"reliability"}
SPC_PLOT = set(_SPC_OPTIONS)
FUNNEL_PLOT = set(_FUNNEL_OPTIONS) | set(_CATERPILLAR_OPTIONS) | {"kind"}
EVERY_NAME = (QIC | FUNNEL | SENSITIVITY | ROLLUP | SPC_PLOT | FUNNEL_PLOT | _params(paretochart)
              | _params(bchart) | _params(design) | _params(analyze))

# Arguments methods.md describes as planned, not yet built.
PLANNED = {"strata"}

# Arguments whose values the docs quote, and the values the code accepts.
CHOICES = {
    "chart": set(CHARTS),
    "method": set(METHODS),
    "measure": set(MEASURES),
    "signal": set(SIGNALS),
    "tau_method": set(TAU_METHODS),
    "worse": {"higher", "lower"},
    "label_signals": {v for v in LABEL_SIGNALS if v},
    "runs_highlight": {"localized", "all", "none"},
    "scales": {"fixed", "free", "free_x", "free_y"},
    "benchmark": {"abc", "eb"},
    "compare_to": {"peers", "model"},
}


# --- What the code produces --------------------------------------------------------

def _spc_results():
    rng = np.random.default_rng(1)
    months = pd.date_range("2022-01-01", periods=24, freq="MS")
    df = pd.DataFrame({
        "month": np.tile(months, 2), "unit": np.repeat(["A", "B"], 24),
        "num": rng.poisson(20, 48), "den": rng.integers(80, 120, 48),
        "phase": np.tile(["before"] * 12 + ["after"] * 12, 2),
        "note": [""] * 47 + ["new protocol"], "who": "x",
    })
    one = df[df.unit == "A"]
    yield qic(one, x="month", y="num", n="den", chart="p", label="note", hover=["who"])
    yield qic(one, x="month", y="num", chart="i", method="nhs", worse="higher", target=15,
              notes="note", part="phase")
    yield qic(one, x="month", y="num", chart="run", freeze=12, exclude=[3])
    yield qic(df, x="month", y="num", n="den", chart="u", facets=["unit"])
    yield qic(y=rng.normal(10, 1, 40), chart="xbar", x=np.repeat(np.arange(10), 4))


def _funnel_results():
    rng = np.random.default_rng(2)
    units = [f"P{i:02d}" for i in range(30)]
    exp = rng.uniform(2, 30, 30)
    oe = pd.DataFrame({"unit": units, "obs": rng.poisson(exp), "exp": exp, "name": units,
                       "svc": ["A", "B"] * 15})
    yield funnel(oe, y="obs", n="exp", measure="oe", unit="unit", label="name", hover=["svc"],
                 worse="higher", benchmark="abc")
    yield funnel(oe, y="obs", n="exp", measure="oe", unit="unit", facets="svc", signal="fdr")
    cases = rng.integers(20, 300, 30)
    prop = pd.DataFrame({"unit": units, "y": rng.binomial(cases, 0.2), "n": cases})
    yield funnel(prop, y="y", n="n", measure="proportion", unit="unit", tau_method="cqc")
    stays = pd.DataFrame({"unit": np.repeat(units, 8), "los": rng.gamma(2, 2.5, 240),
                          "exp": rng.uniform(3, 7, 240)})
    yield funnel(stays, y="los", n="exp", measure="oe", unit="unit",
                 within_dispersion="estimate")
    yield funnel(stays, y="los", measure="mean", unit="unit")
    yield funnel(oe.assign(phi=rng.uniform(1, 3, 30)), y="obs", n="exp", measure="oe",
                 unit="unit", within_dispersion="phi")


def _keys(results) -> set[str]:
    keys: set[str] = set()
    for r in results:
        keys |= set(r.summary)
        for nested in r.summary.values():
            if isinstance(nested, dict):
                keys |= set(nested)
            elif isinstance(nested, list) and nested and isinstance(nested[0], dict):
                keys |= set(nested[0])
    return keys


SPC_RESULTS = list(_spc_results())
FUNNEL_RESULTS = list(_funnel_results())
SPC_COLUMNS = set().union(*(r.data.columns for r in SPC_RESULTS))
FUNNEL_COLUMNS = set().union(*(r.data.columns for r in FUNNEL_RESULTS))
# Columns that exist only because of the test data (facet names, hover columns).
DATA_COLUMNS = {"unit", "who", "svc"}
SUMMARY_KEYS = _keys(SPC_RESULTS) | _keys(FUNNEL_RESULTS) | set(
    funnel_sensitivity(pd.DataFrame({"u": list("abcdefghij"), "y": range(1, 11),
                                     "n": [20] * 10}),
                       y="y", n="n", measure="proportion", unit="u").columns)


# --- What the docs say -------------------------------------------------------------

def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _python_blocks(text: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", text, flags=re.S)


def _prose(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _plot_options_for(node: ast.Call) -> set[str]:
    """plot() options for the result plot() is called on, when the call shows it."""
    receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
    if isinstance(receiver, ast.Call):
        name = _call_name(receiver)
        if name == "qic":
            return SPC_PLOT
        if name in ("funnel", "qikit_funnel"):
            return FUNNEL_PLOT
    return SPC_PLOT | FUNNEL_PLOT


def _doc_ids(paths) -> list:
    return [pytest.param(p, id=str(p.relative_to(ROOT))) for p in paths]


@pytest.mark.parametrize("path", _doc_ids(DOCS))
def test_code_examples_parse_and_use_real_arguments(path):
    allowed = {"qic": QIC, "funnel": FUNNEL, "qikit_funnel": FUNNEL,
               "funnel_sensitivity": SENSITIVITY, "funnel_rollup": ROLLUP,
               "min_denominator": MIN_DENOMINATOR}
    problems = []
    for block in _python_blocks(_text(path)):
        tree = ast.parse(block)  # a doc example that does not parse is itself a defect
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            valid = _plot_options_for(node) if name == "plot" else allowed.get(name or "")
            if valid is None:
                continue
            for kw in node.keywords:
                if kw.arg is not None and kw.arg not in valid:
                    problems.append(f"{name}({kw.arg}=...)")
                if kw.arg in CHOICES and isinstance(kw.value, ast.Constant):
                    if kw.value.value not in CHOICES[kw.arg] | {None}:
                        problems.append(f"{name}({kw.arg}={kw.value.value!r})")
    assert not problems, f"{path.name}: {problems}"


@pytest.mark.parametrize("path", _doc_ids(DOCS))
def test_inline_arguments_and_values_exist(path):
    problems = []
    for name, value in re.findall(r"`(\w+)=(\"[^\"`]*\"|[^`,)\s]*)", _prose(_text(path))):
        if name.isupper():
            continue  # SQL and environment settings, not qikit arguments
        if name not in EVERY_NAME | PLANNED:
            problems.append(f"{name}=")
        elif name in CHOICES and value.startswith('"'):
            if value.strip('"') not in CHOICES[name]:
                problems.append(f"{name}={value}")
    assert not problems, f"{path.name}: {problems}"


@pytest.mark.parametrize("path", _doc_ids(DOCS))
def test_summary_keys_exist(path):
    named = set(re.findall(r"summary\[[\"'](\w+)[\"']\]", _text(path)))
    assert not named - SUMMARY_KEYS, f"{path.name}: {sorted(named - SUMMARY_KEYS)}"


@pytest.mark.parametrize("path", _doc_ids(DOCS))
def test_columns_read_in_examples_exist(path):
    named: set[str] = set()
    for block in _python_blocks(_text(path)):
        named |= set(re.findall(r"\.data\.(\w+)", block))
        for group in re.findall(r"\.data\[\[([^\]]+)\]\]", block):
            named |= set(re.findall(r"[\"'](\w+)[\"']", group))
    columns = SPC_COLUMNS | FUNNEL_COLUMNS
    named -= {"columns", "to_csv", "head", "query", "loc", "iloc"}
    assert not named - columns, f"{path.name}: {sorted(named - columns)}"


@pytest.mark.parametrize("skill, columns", [
    ("spc-monitoring", SPC_COLUMNS), ("provider-funnels", FUNNEL_COLUMNS),
])
def test_skill_column_lists_match_the_code(skill, columns):
    text = _text(ROOT / "skills" / skill / "SKILL.md")
    section = text.split("## Columns of `r.data`", 1)[1].strip().split("\n\n", 1)[0]
    listed = {name for chunk in re.findall(r"`([^`]+)`", section)
              for name in re.findall(r"\b([a-z_][a-z0-9_]*)\b(?!=)", chunk)}
    listed -= EVERY_NAME - columns  # argument names that say when a column appears
    assert not listed - columns, f"listed but never produced: {sorted(listed - columns)}"
    missing = columns - listed - DATA_COLUMNS
    assert not missing, f"produced but not listed: {sorted(missing)}"
