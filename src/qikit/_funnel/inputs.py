"""
_funnel/inputs.py — funnel()'s arguments as one normalized frame: columns, facets,
exclusions, and the inputs of a mean measure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..validate import _did_you_mean, check_column, numbers
from .constants import (
    _CASES,
    _COLUMNS,
    _DROP,
    _EXCL,
    _LABEL,
    _MAXN,
    _MAXY,
    _N,
    _PHI,
    _SS,
    _UNIT,
    _Y,
)


def _mean_inputs(data, n, cases, sum_sq, max_case_y, max_case_n, within_dispersion):
    """
    measure="mean" defaults (methods §4.19): n is the case count (1 per row when
    omitted), cases= is that same n, max_case_n is 1, and φ is always estimated or given
    per provider, never a scalar the caller would have to know in y's units.
    """
    if within_dispersion is None:
        within_dispersion = "estimate"
    elif not isinstance(within_dispersion, str):
        raise ValueError(
            "measure='mean' estimates within_dispersion from the cases (the variance-to-"
            "mean ratio of one case, in y's units), so a number cannot be supplied. Leave "
            "it unset, or pass a column of per-provider phi."
        )
    if max_case_n is not None:
        raise ValueError(
            "measure='mean' takes max_case_y= alone: the worst single case's amount; its "
            "denominator is always one case."
        )
    if sum_sq is not None:
        if n is None:
            raise ValueError(
                "measure='mean' with sum_sq= needs n=: each provider's number of cases "
                "(COUNT(*)), alongside y = SUM(amount) and sum_sq = SUM(amount * amount)."
            )
        if cases is not None and cases != n:
            raise ValueError("Under measure='mean' n= is the case count; leave cases= unset.")
        cases = n
    elif cases is not None:
        raise ValueError(
            "measure='mean' with provider totals takes n= (the case count) and sum_sq= "
            "(SUM(amount * amount)); cases= is implied by n=."
        )
    return n, cases, max_case_n, within_dispersion


def _check_mean_rows(frame: pd.DataFrame, aggregated: bool) -> None:
    """Amounts ≥ 0, and on case rows one case per row."""
    y = frame[_Y].to_numpy(dtype=float)
    if np.any(np.isfinite(y) & (y < 0)):
        raise ValueError(
            "measure='mean' needs amounts of 0 or more (minutes, cost, days): its "
            "variance grows with the mean. Signed values such as change scores are not "
            "supported."
        )
    if aggregated:
        return
    n = frame[_N].to_numpy(dtype=float)
    if np.any(np.isfinite(n) & (n != 1.0)):
        raise ValueError(
            "measure='mean' on case rows takes one case per row (n = 1, or leave n= "
            "unset). With one row per provider, pass y = SUM(amount), n = COUNT(*) and "
            "sum_sq = SUM(amount * amount), so the spread of single cases can be measured."
        )


def _normalize(data, y, n, unit, label, hover, facets, exclude, extra=None):
    """
    One DataFrame with working columns for unit, y, n, label and exclude, whatever
    form the caller used. Rows sharing a unit (and facet) are summed per provider.
    extra maps working column → caller column name (cases=, sum_sq=, max_case_y=,
    max_case_n=, a within_dispersion column), each numeric and requiring data=.
    """
    extra = {k: v for k, v in (extra or {}).items() if v is not None}
    if extra and data is None:
        raise ValueError(
            "cases=, sum_sq=, max_case_y=, max_case_n= and a within_dispersion column "
            "name columns of data=; pass data= as a DataFrame."
        )
    if data is None:
        if isinstance(y, str) or isinstance(n, str):
            raise ValueError("Without data=, y= and n= must be sequences, not column names.")
        yv = numbers("y", y)
        nv = np.ones(len(yv)) if n is None else numbers("n", n)
        if len(nv) != len(yv):
            raise ValueError(f"n= has {len(nv)} values, but y= has {len(yv)}.")
        frame = pd.DataFrame({_Y: yv, _N: nv})
        k = len(frame)
        for col, values in ((_UNIT, unit), (_LABEL, label)):
            if values is not None:
                if len(values) != k:
                    raise ValueError(f"unit=/label= must have one value per y, got {len(values)}.")
                frame[col] = list(values)
        if facets:
            raise ValueError("facets= needs data= (it names columns).")
        hover_names: list[str] = []
        if hover is not None:
            if not isinstance(hover, dict):
                raise ValueError("Without data=, hover= must be a dict of per-point sequences.")
            for name, values in hover.items():
                frame[str(name)] = list(values)
                hover_names.append(str(name))
    else:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("data= must be a pandas DataFrame.")
        for name, col in (("y", y), ("n", n), ("unit", unit), ("label", label),
                          *(("facets", f) for f in facets)):
            check_column(data, name, col, required=name == "y", column_only=True)
        frame = pd.DataFrame({_Y: numbers("y", data[y]),
                              _N: 1.0 if n is None else numbers("n", data[n])},
                             index=data.index)
        if unit is not None:
            frame[_UNIT] = data[unit].to_numpy()
        if label is not None:
            frame[_LABEL] = data[label].to_numpy()
        for col in facets:
            frame[col] = data[col].to_numpy()
        hover_names = [hover] if isinstance(hover, str) else list(hover or [])
        for name in hover_names:
            check_column(data, "hover", name, column_only=True)
            if name in _COLUMNS:
                raise ValueError(f"hover= column {name!r} collides with a column funnel() writes.")
            frame[name] = data[name].to_numpy()
        for key, col in extra.items():
            what = {_PHI: "within_dispersion", _CASES: "cases", _SS: "sum_sq",
                    _MAXY: "max_case_y", _MAXN: "max_case_n"}[key]
            if not isinstance(col, str) or col not in data.columns:
                raise ValueError(
                    f"{what}= must name a column of data, got {col!r}."
                    + (" A number, or 'estimate', is also accepted." if key == _PHI else "")
                    + (_did_you_mean(col, data.columns) if isinstance(col, str) else "")
                )
            frame[key] = numbers(what, data[col])
        frame = frame.reset_index(drop=True)

    if _UNIT not in frame.columns:
        frame[_UNIT] = np.arange(1, len(frame) + 1)
    # A row missing its numerator, denominator or unit cannot be placed: it leaves the
    # sums (never counting as zero events) and is counted in summary["n_rows_dropped"].
    incomplete = (frame[_Y].isna() | frame[_N].isna() | frame[_UNIT].isna()).to_numpy()
    frame[_DROP] = incomplete
    frame.loc[incomplete, [_Y, _N]] = np.nan
    if incomplete.all() and len(frame):
        raise ValueError(
            "No row has all of y=, n= and unit=: every row is missing at least one, so "
            "there is nothing to compare. Check the columns passed as y=, n= and unit=."
        )

    if exclude is not None:
        if isinstance(exclude, str):
            if data is None or exclude not in data.columns:
                raise ValueError("exclude= as a string must name a boolean column of data.")
            frame[_EXCL] = data[exclude].fillna(False).to_numpy(dtype=bool)
        else:
            ids = set(exclude)
            unknown = ids - set(frame[_UNIT])
            if unknown:
                raise ValueError(f"exclude= lists unit(s) not in the data: {sorted(map(str, unknown))}.")
            frame[_EXCL] = frame[_UNIT].isin(ids).to_numpy()
    return frame, hover_names
