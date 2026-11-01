"""
validate.py — argument checks shared by qic() and funnel(), with messages that name the fix.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

WORSE = (None, "higher", "lower")


def check_choice(name: str, value: Any, valid: tuple, hint: str = "") -> Any:
    """value if it is one of valid, else a ValueError listing them."""
    if value not in valid:
        raise ValueError(f"{name} must be one of {valid}, got {value!r}.{hint}")
    return value


def check_column(data: pd.DataFrame, name: str, col: Any, required: bool = False) -> None:
    """With data=, an argument that names a column must name one that exists."""
    if col is None:
        if required:
            raise ValueError(f"{name}= is required: a column of data.")
        return
    if isinstance(col, str):
        if col not in data.columns:
            raise ValueError(f"{name}={col!r} is not a column of data. Columns: {list(data.columns)}.")
    elif name in ("y", "n"):
        raise ValueError(f"With data=, {name}= names a column, got {type(col).__name__}.")


def check_facet_names(facets: list[str], output: tuple, fn: str) -> None:
    """A facet column is copied into result.data, so it cannot share a name with one there."""
    clash = [f for f in facets if f in output]
    if clash:
        raise ValueError(f"facets= column(s) {clash} share a name with a column {fn}() writes "
                         f"to result.data. Rename them in data first.")


def split_facets(facets: Any) -> list[str]:
    """facets= as a list of column names (a single name, a list, or None)."""
    if facets is None:
        return []
    if isinstance(facets, str):
        return [facets]
    cols = list(facets)
    if not all(isinstance(c, str) for c in cols):
        raise ValueError(f"facets= is a column name or a list of them, got {facets!r}.")
    return cols


def check_levels(name: str, levels: Any, outer_wider: bool) -> tuple[float, float]:
    """
    limits= is (outer, inner) coverage, outer the wider: (0.998, 0.95). fdr_levels= is
    (outlier, alert) false discovery rate, outlier the stricter: (0.05, 0.10).
    """
    ok = (
        isinstance(levels, (tuple, list)) and len(levels) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 < v < 1.0
                for v in levels)
        and (levels[0] > levels[1] if outer_wider else levels[0] < levels[1])
        and (not outer_wider or all(v > 0.5 for v in levels))
    )
    if not ok:
        example = "(0.998, 0.95)" if outer_wider else "(0.05, 0.10)"
        order = "outer wider than inner, both above 0.5" if outer_wider else \
            "outlier stricter than alert"
        raise ValueError(f"{name} must be two numbers between 0 and 1, {order}, e.g. "
                         f"{example}. Got {levels!r}.")
    return float(levels[0]), float(levels[1])


def check_number(name: str, value: Any, minimum: float = 0.0, strict: bool = False) -> float:
    ok = (isinstance(value, (int, float)) and not isinstance(value, bool)
          and math.isfinite(value) and (value > minimum if strict else value >= minimum))
    if not ok:
        bound = f"> {minimum:g}" if strict else f">= {minimum:g}"
        raise ValueError(f"{name} must be a number {bound}, got {value!r}.")
    return float(value)


def reject_removed(
    fn: str, removed: dict[str, Any], renamed: dict[str, str], display: tuple,
    other: tuple = (), extra: dict[str, str] | None = None,
) -> None:
    """
    A TypeError for keyword arguments a function does not take, naming where each went:
    a 1.0 rename, a display option that moved to plot(), or another function's argument.
    """
    reasons = []
    for name in removed:
        if name in renamed:
            reasons.append(f"{name}=: it is now {renamed[name]}")
        elif name in display:
            reasons.append(f"{name}=: it is a display option, {fn}(...).plot({name}=...)")
        elif extra and name in extra:
            reasons.append(f"{name}=: {extra[name]}")
        elif name in other:
            other_fn = "funnel" if fn == "qic" else "qic"
            reasons.append(f"{name}=: it is an argument of {other_fn}()")
        else:
            raise TypeError(f"{fn}() got an unexpected keyword argument {name!r}")
    raise TypeError(f"{fn}() does not take " + "; ".join(reasons) + ".")
