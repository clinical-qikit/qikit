"""
spc.py — qic(): one measure over time, with control limits and signals.

    from qikit import qic
    r = qic(df, x="month", y="deaths", n="admissions", chart="p")
    r.data          # one row per subgroup: limits, signal, runs_signal
    r.summary       # the rules that fired, and how the limits were set
    r.plot()        # a Plotly figure

The pipeline, top to bottom: normalize the inputs, aggregate rows into subgroups by x,
set the baseline (exclude=, freeze=), compute each part's center line and limits
(core/shewhart.py), find patterns (core/rules.py), and assemble the table. Comparing
providers with each other is a funnel plot: qikit.funnel().
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .core.rules import METHODS, ZONE_METHODS, apply_rules
from .core.shewhart import CHARTS, RATE_CHARTS, SUBGROUP_CHARTS, T_POWER, shewhart
from .results import SPCResult
from .validate import (
    WORSE, check_choice, check_column, check_facet_names, reject_removed, split_facets,
)

# Columns qic() writes to result.data; facet and hover columns cannot reuse them.
OUTPUT_COLUMNS = (
    "x", "label", "y", "n", "cl", "ucl", "lcl", "ucl_95", "lcl_95", "signal", "runs_signal",
    "variation", "special_cause", "part", "baseline", "excluded", "target", "notes",
)

AGG_FUNS = ("mean", "median", "sum")
PERIODS = {"day": "D", "week": "W", "month": "MS", "quarter": "QS", "year": "YS"}

# What qic() took before 1.0, and where each went. Display options moved to plot().
_RENAMED = {
    "cl": "center=",
    "point_labels": "label=",
    "hover_extra": "hover=",
}
_DISPLAY = (
    "title", "subtitle", "caption", "xlab", "ylab", "part_labels", "show_labels",
    "show_95", "show_grid", "show_x_labels", "decimals", "point_size", "x_format",
    "x_angle", "x_pad", "x_order", "y_expand", "height", "width", "y_neg", "y_percent",
    "connect", "runs_highlight", "label_signals", "x_range", "y_range", "styles",
    "show_legend", "flip", "nrow", "ncol", "scales",
)
_GONE = {
    "print_summary": "removed; print(result) describes the chart",
    "y_percent_accuracy": "removed (it had no effect); plot(decimals=...) sets the precision",
    "strip_horizontal": "removed (it had no effect)",
}
_FUNNEL_ONLY = ("funnel", "signal_side", "signal_method", "limit_method", "x_spacing",
                "x_log", "levels", "fdr_levels", "within_dispersion")


def qic(
    data: pd.DataFrame | None = None,
    *,
    x: Any = None,
    y: Any,
    n: Any = None,
    chart: str = "run",
    method: str = "anhoej",
    freeze: int | None = None,
    part: Any = None,
    exclude: Any = None,
    center: float | None = None,
    target: Any = None,
    worse: str | None = None,
    agg_fun: str = "mean",
    x_period: str | None = None,
    multiply: float = 1.0,
    facets: str | list[str] | None = None,
    label: Any = None,
    hover: Any = None,
    notes: Any = None,
    **removed: Any,
) -> SPCResult:
    """
    A statistical process control chart: one measure over time, judged against its own
    past. Returns an SPCResult; result.data is the table, result.plot() the figure.

    Choosing the chart
    ------------------
    | You have, per period                         | chart=  | y=, n=                      |
    |----------------------------------------------|---------|-----------------------------|
    | any measure, few assumptions (start here)    | "run"   | y                           |
    | one continuous value (LOS, wait time, O/E)   | "i"     | y                           |
    | events out of cases (H&P in 24 h, mortality) | "p"     | y=events, n=cases           |
    | the same, n in the thousands (over-dispersed)| "pp"    | y=events, n=cases (Laney)   |
    | events over exposure (infections/line-days)  | "u"     | y=events, n=exposure        |
    | the same, exposure in the thousands          | "up"    | y=events, n=exposure (Laney)|
    | an O/E ratio over time                       | "u"     | y=observed, n=expected      |
    | counts with constant opportunity             | "c"     | y=count                     |
    | several raw values per period (subgroups)    | "xbar"  | y=raw values, x=period      |
    |   and their spread                           | "s"     | y=raw values, x=period      |
    | cases between rare events (never events)     | "g"     | y=cases between             |
    | days between rare events                     | "t"     | y=days between              |
    | the moving range of an i chart               | "mr"    | y                           |

    With data=, x=, y=, n= name columns, and rows sharing an x are aggregated into one
    subgroup: events and denominators summed, raw values averaged (agg_fun=). x is
    sorted when it is a number or a date; text x keeps its order. Without data=, they
    are sequences, one value per point.

    Choosing the rules (method=)
    ----------------------------
    - "anhoej" (default): qicharts2's run rules, an unusually long run on one side of
      the center line or unusually few crossings of it (Anhøj & Olesen 2014).
    - "nhs": NHS England's Making Data Count, for XmR (chart="i") boards: 7 on one side,
      7 rising or falling, 2 of 3 near a limit. Pass worse= to class each special cause
      as improving or concerning, and target= for the assurance verdict.
    - "ihi": Provost & Murray's rules (shift, trend, and on Shewhart charts the zone
      rules). "weco", "nelson": the classic zone rules.

    Reading the result
    ------------------
    result.data, one row per point in plotted order:

    - x, label, y (after multiply=), n (when given; the subgroup size on xbar/s).
    - cl, ucl, lcl: center line and 3σ limits; ucl_95, lcl_95: the 2σ lines.
    - signal: "outlier" beyond ucl/lcl, else "none".
    - runs_signal: the point is part of a pattern the rules found (a long run, a trend).
      Too few crossings is a property of the whole series: summary["crossings_signal"].
    - variation (method="nhs"): "improving", "concerning", "neutral" (no worse=) or
      "common", Making Data Count's reading of each point.
    - part, baseline (used to set the limits), excluded, target, notes, hover columns,
      and one column per facets= column.

    result.summary: signals (any outlier or pattern), n_outlier, runs_signal, the rule
    method's own keys (anhoej: n_useful, longest_run, longest_run_max, n_crossings,
    n_crossings_min, longest_run_signal, crossings_signal; others: rules_fired), sigma_z
    (pp/up), parts (one dict per part; the top level describes the last part, the
    current process), variation and assurance (method="nhs"), and by_facet.

    Parameters
    ----------
    data : a DataFrame, or None to pass sequences.
    x, y, n : columns of data (or sequences). n= is required on p/pp/u/up; on any other
        chart it divides y, as in qicharts2 (an i chart of a rate).
    chart, method : see above.
    freeze : the baseline ends at this point (1-based): the limits come from points
        1..freeze and later points are judged against them.
    part : split the chart into parts, each with its own center line, limits and rules:
        the point(s) where each part ends (1-based, as freeze=), or a column whose value
        changes between parts (e.g. "before"/"after").
    exclude : points to leave out of the limits and the rules (drawn faded): a column of
        booleans, or 1-based positions.
    center : a fixed center line instead of the baseline's.
    target : a target line: a number, or a column.
    worse : "higher" or "lower": which direction is bad, for method="nhs" (improving or
        concerning special cause; assurance against target=).
    agg_fun : how raw values in one subgroup combine when there is no n=: "mean",
        "median" or "sum".
    x_period : aggregate a date x into periods: "day", "week", "month", "quarter",
        "year" (or a pandas frequency).
    multiply : scale y and the limits, e.g. 1000 for a rate per 1,000.
    facets : one column, or a list of columns: one chart per value (or combination).
        result.data keeps those columns, so it is ready to write back to a table.
    label : display name per point (a column or sequence); hover : extra tooltip
        columns; notes : annotations per point (a column or sequence).

    Display options (title, axis labels, styles, ...) are arguments of result.plot().
    """
    if removed:
        reject_removed("qic", removed, _RENAMED, _DISPLAY, _FUNNEL_ONLY, _GONE)
    chart = check_choice("chart", chart.lower().strip() if isinstance(chart, str) else chart,
                         CHARTS, hint=_chart_hint(chart))
    method = check_choice("method", method, METHODS)
    worse = check_choice("worse", worse, WORSE)
    agg_fun = check_choice("agg_fun", agg_fun, AGG_FUNS)
    if freeze is not None and part is not None:
        raise ValueError("freeze= and part= cannot be combined: freeze sets one baseline "
                         "for the whole series, part= gives each part its own.")
    if not (isinstance(multiply, (int, float)) and not isinstance(multiply, bool)
            and math.isfinite(multiply) and multiply > 0):
        raise ValueError(f"multiply must be a positive number, got {multiply!r}.")
    if method in ZONE_METHODS and chart == "run":
        raise ValueError(
            f"method={method!r} reads the 1 and 2 sigma zones, and a run chart has no limits. "
            f"Use chart='i' (an XmR chart), or method='anhoej' or 'ihi' on a run chart."
        )

    frame = _normalize(data, x, y, n, label, hover, notes, exclude, part, target, facets,
                       x_period)
    facet_cols = split_facets(facets)
    check_facet_names(facet_cols, OUTPUT_COLUMNS, "qic")
    hover_names = _hover_names(hover, data)
    settings = dict(
        chart=chart, method=method, freeze=freeze, part=part, exclude=exclude,
        center=center, worse=worse, agg_fun=agg_fun, x_period=x_period,
        multiply=float(multiply), has_n=n is not None, target=target, hover=hover_names,
    )
    if not facet_cols:
        table, summary = _chart(frame, settings)
    else:
        tables, by_facet = [], {}
        for key, rows in frame.groupby(facet_cols, sort=False, dropna=False):
            key = key if isinstance(key, tuple) else (key,)
            t, s = _chart(rows, settings)
            for i, (col, val) in enumerate(zip(facet_cols, key)):
                t.insert(i, col, val)
            tables.append(t)
            by_facet[" / ".join(str(v) for v in key)] = s
        table = pd.concat(tables, ignore_index=True)
        summary = {
            "chart": chart, "method": method,
            "n_obs": sum(s["n_obs"] for s in by_facet.values()),
            "signals": any(s["signals"] for s in by_facet.values()),
            "n_outlier": sum(s["n_outlier"] for s in by_facet.values()),
            "by_facet": by_facet,
        }
    meta = {
        "facets": facet_cols, "worse": worse, "hover": hover_names,
        "x_name": x if isinstance(x, str) else None,
        "y_name": y if isinstance(y, str) else None,
        "n_name": n if isinstance(n, str) else None,
        "percent": chart in ("p", "pp") and multiply == 1.0,
    }
    return SPCResult(data=table, summary=summary, chart=chart, method=method, _meta=meta)


def _chart_hint(chart: Any) -> str:
    if chart in ("oe", "oep"):
        return (" Comparing providers' O/E is a funnel plot: qikit.funnel(..., measure='oe'). "
                "A monthly O/E series is qic(chart='u', y=observed, n=expected).")
    if chart == "ip":
        return " An i chart of a rate is qic(chart='i', y=events, n=denominator)."
    return ""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

_X, _Y, _N, _LABEL, _NOTES, _EXCL, _PART, _TARGET = (
    "__x", "__y", "__n", "__label", "__notes", "__exclude", "__part", "__target",
)


def _normalize(data, x, y, n, label, hover, notes, exclude, part, target, facets, x_period):
    """One row per input row, with working columns; positional arguments stay positional."""
    if data is None:
        if any(isinstance(v, str) for v in (x, y, n, label, notes, facets)):
            raise ValueError("Column names need data=: pass data=df, or pass sequences.")
        y_arr = np.asarray(y, dtype=float) if y is not None else np.array([])
        k = len(y_arr)
        frame = pd.DataFrame({_Y: y_arr})
        frame[_X] = list(x) if x is not None else list(range(1, k + 1))
        for col, values, name in ((_N, n, "n"), (_LABEL, label, "label"),
                                  (_NOTES, notes, "notes")):
            if values is not None:
                if np.ndim(values) == 0:  # one value for every point
                    values = [values] * k
                vals = np.asarray(values, dtype=float) if col == _N else list(values)
                if len(vals) != k:
                    raise ValueError(f"{name}= has {len(vals)} values, but y= has {k}.")
                frame[col] = vals
        if len(frame[_X]) != k:
            raise ValueError(f"x= has {len(frame[_X])} values, but y= has {k}.")
        if hover is not None:
            if not isinstance(hover, dict):
                raise ValueError("Without data=, hover= is a dict of per-point sequences.")
            for name, values in hover.items():
                frame[str(name)] = list(values)
    else:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("data= must be a pandas DataFrame (or None, to pass sequences).")
        check_column(data, "y", y, required=True)
        for name, col in (("x", x), ("n", n)):
            check_column(data, name, col)
        for col in split_facets(facets):
            check_column(data, "facets", col)
        frame = pd.DataFrame({_Y: pd.to_numeric(data[y], errors="coerce").to_numpy(dtype=float)},
                             index=data.index)
        frame[_X] = data[x].to_numpy() if isinstance(x, str) else (
            list(x) if x is not None else np.arange(1, len(data) + 1))
        if n is not None:
            frame[_N] = pd.to_numeric(data[n], errors="coerce").to_numpy(dtype=float)
        for col, values, name in ((_LABEL, label, "label"), (_NOTES, notes, "notes")):
            if values is not None:
                frame[col] = _column_or_sequence(data, name, values)
        for col in split_facets(facets):
            frame[col] = data[col].to_numpy()
        for name in _hover_names(hover, data):
            frame[name] = data[name].to_numpy()
        if isinstance(exclude, str):
            check_column(data, "exclude", exclude)
            frame[_EXCL] = data[exclude].fillna(False).to_numpy(dtype=bool)
        if isinstance(part, str):
            check_column(data, "part", part)
            frame[_PART] = data[part].to_numpy()
        if isinstance(target, str):
            check_column(data, "target", target)
            frame[_TARGET] = pd.to_numeric(data[target], errors="coerce").to_numpy(dtype=float)
        elif target is not None and np.ndim(target) == 1:
            frame[_TARGET] = _column_or_sequence(data, "target", target).astype(float)
        frame = frame.reset_index(drop=True)
    if x_period is not None:
        frame[_X] = pd.to_datetime(frame[_X])
    return frame


def _column_or_sequence(data: pd.DataFrame, name: str, values) -> np.ndarray:
    """A column of data, one value per row of data, or one value for every row."""
    if isinstance(values, str):
        check_column(data, name, values)
        return data[values].to_numpy()
    if np.ndim(values) == 0:
        return np.full(len(data), values, dtype=object)
    values = np.asarray(list(values), dtype=object)
    if len(values) != len(data):
        raise ValueError(f"{name}= has {len(values)} values for {len(data)} rows of data.")
    return values


def _hover_names(hover, data) -> list[str]:
    if hover is None:
        return []
    if data is None:
        return [str(k) for k in hover] if isinstance(hover, dict) else []
    names = [hover] if isinstance(hover, str) else list(hover)
    for name in names:
        check_column(data, "hover", name)
    clash = [name for name in names if name in OUTPUT_COLUMNS]
    if clash:
        raise ValueError(f"hover= column(s) {clash} collide with columns qic() writes; rename them.")
    return names


# ---------------------------------------------------------------------------
# One chart
# ---------------------------------------------------------------------------

def _chart(frame: pd.DataFrame, s: dict) -> tuple[pd.DataFrame, dict[str, Any]]:
    chart = s["chart"]
    pts = _aggregate(frame, s)
    k = len(pts)
    if k == 0:
        raise ValueError("y= has no values.")
    y_raw, n = pts[_Y].to_numpy(dtype=float), (
        pts[_N].to_numpy(dtype=float) if _N in pts else None)

    # The plotted value: events over denominators wherever n= is given (as qicharts2).
    if chart in RATE_CHARTS and n is None:
        raise ValueError(f"chart={chart!r} needs n= (the denominator: cases or exposure).")
    sizes = sd = None
    if chart in SUBGROUP_CHARTS:
        y, sizes, sd = y_raw, pts["__size"].to_numpy(dtype=float), pts["__sd"].to_numpy()
        if chart == "s":
            y = sd
    elif n is not None:
        if chart in RATE_CHARTS:
            _check_rates(chart, y_raw, n)
        with np.errstate(divide="ignore", invalid="ignore"):
            y = np.where(n > 0, y_raw / n, np.nan)
    else:
        y = y_raw

    excluded = _excluded(pts, s["exclude"], k)
    baseline = ~excluded
    if s["freeze"] is not None:
        f = _position(s["freeze"], k, "freeze")
        baseline[f:] = False
    ends = _part_ends(pts, s["part"], k)

    if chart == "mr":
        if k < 2:
            raise ValueError("chart='mr' needs at least 2 points: a moving range spans two.")
        y = np.concatenate([[np.nan], np.abs(np.diff(y))])
        y[ends] = np.nan  # each part's ranges start afresh, as in qicharts2
        excluded = excluded | np.concatenate([[False], excluded[:-1]])
        baseline = baseline & np.concatenate([[False], baseline[:-1]])
    if chart == "t":
        if np.any(y[np.isfinite(y)] < 0):
            raise ValueError("chart='t' needs times between events that are 0 or more.")
        y_calc = y ** (1.0 / T_POWER)
    else:
        y_calc = y
    y_signal = np.where(excluded, np.nan, y_calc)
    columns: dict[str, np.ndarray] = {k_: np.full(k, np.nan) for k_ in ("cl", "ucl", "lcl", "ucl_95", "lcl_95")}
    outlier = np.zeros(k, dtype=bool)
    runs = np.zeros(k, dtype=bool)
    cause: np.ndarray | None = None
    direction = np.zeros(k)
    part_id = np.zeros(k, dtype=int)
    parts: list[dict[str, Any]] = []
    categorical = all(isinstance(v, str) for v in pts[_X])
    for p, (start, end) in enumerate(zip([0] + ends, ends + [k])):
        seg = slice(start, end)
        part_id[seg] = p + 1
        lim = shewhart(
            "i" if chart == "t" else chart, y_calc[seg],
            sizes[seg] if sizes is not None else (n[seg] if n is not None else None),
            baseline[seg], s["center"] if chart != "t" or s["center"] is None
            else s["center"] ** (1.0 / T_POWER),
            sd[seg] if sd is not None else None, categorical,
            mdc=s["method"] == "nhs" and chart == "i",
        )
        ys = y_signal[seg]
        with np.errstate(invalid="ignore"):
            outlier[seg] = (ys > lim.ucl) | (ys < lim.lcl)
        has_limits = bool(np.isfinite(lim.ucl).any())
        rules = apply_rules(s["method"], ys, lim.cl, lim.sigma, lim.ucl, lim.lcl, has_limits)
        runs[seg] = rules.points
        if rules.cause is not None:
            if cause is None:
                cause = np.full(k, "", dtype=object)
            cause[seg], direction[seg] = rules.cause, rules.direction
        for name in columns:
            columns[name][seg] = getattr(lim, name)
        parts.append({
            "part": p + 1, "n_obs": int(np.isfinite(ys).sum()),
            "n_baseline": int((baseline[seg] & np.isfinite(y_calc[seg])).sum()),
            "n_outlier": int(outlier[seg].sum()), **rules.summary, **lim.info,
        })

    if chart == "t":
        for name in columns:
            v = columns[name]
            columns[name] = np.where(np.isfinite(v), np.maximum(v, 0.0) ** T_POWER, np.nan)

    m = s["multiply"]
    table = pd.DataFrame({"x": pts[_X].to_numpy()})
    if _LABEL in pts:
        table["label"] = pts[_LABEL].to_numpy()
    table["y"] = y * m
    if sizes is not None:
        table["n"] = sizes
    elif n is not None:
        table["n"] = n
    for name, v in columns.items():
        table[name] = v * m
    table["signal"] = np.where(outlier, "outlier", "none")
    table["runs_signal"] = runs
    if cause is not None:
        table["variation"] = _variation(direction, s["worse"])
        table["special_cause"] = cause
    if ends:
        table["part"] = _part_labels(pts, part_id, s["part"])
    table["baseline"] = baseline
    table["excluded"] = excluded
    target = _target(pts, s["target"], k)
    if target is not None:
        table["target"] = target * m
    if _NOTES in pts:
        table["notes"] = ["" if (v is None or (isinstance(v, float) and math.isnan(v)))
                          else str(v) for v in pts[_NOTES]]
    for col in pts.columns:
        if col in s["hover"] and col not in table:
            table[col] = pts[col].to_numpy()

    last = parts[-1]
    summary: dict[str, Any] = {
        "chart": chart, "method": s["method"],
        "n_obs": int(np.isfinite(y).sum()),
        "n_baseline": int((baseline & np.isfinite(y_calc)).sum()),
        "signals": bool(outlier.any() or any(p_["runs_signal"] for p_ in parts)),
        "n_outlier": int(outlier.sum()),
        **{k_: v for k_, v in last.items() if k_ not in ("part", "n_obs", "n_baseline",
                                                        "n_outlier")},
        "runs_signal": any(p_["runs_signal"] for p_ in parts),
        "freeze": s["freeze"],
        "excluded": [int(i) + 1 for i in np.flatnonzero(excluded)],
    }
    if len(parts) > 1:
        summary["parts"] = parts
    if cause is not None:
        summary["variation"] = str(table["variation"].iloc[-1])
        summary["special_cause"] = str(cause[-1])
        summary["assurance"] = _assurance(target, columns, s["worse"])
    return table, summary


def _aggregate(frame: pd.DataFrame, s: dict) -> pd.DataFrame:
    """One row per subgroup (x value), in plotted order."""
    chart = s["chart"]
    grouped = (s["x_period"] is not None or chart in SUBGROUP_CHARTS
               or bool(frame[_X].duplicated().any()))
    if not grouped:
        return _sorted(frame).reset_index(drop=True)
    if s["x_period"] is not None:
        freq = PERIODS.get(str(s["x_period"]).lower(), s["x_period"])
        g = frame.groupby(pd.Grouper(key=_X, freq=freq))
    else:
        g = frame.groupby(_X, sort=_sortable(frame[_X]), dropna=True)
    agg: dict[str, Any] = {}
    if chart in SUBGROUP_CHARTS:
        agg[_Y] = g[_Y].mean() if s["agg_fun"] == "mean" else g[_Y].agg(s["agg_fun"])
        agg["__size"] = g[_Y].count().astype(float)
        agg["__sd"] = g[_Y].std(ddof=1)
        if (agg["__size"] < 2).all():
            raise ValueError(f"chart={chart!r} needs subgroups of 2 or more raw values per x.")
    elif s["has_n"] or chart in RATE_CHARTS:
        agg[_Y] = g[_Y].sum(min_count=1)
        agg[_N] = g[_N].sum(min_count=1)
    else:
        agg[_Y] = g[_Y].agg(s["agg_fun"])
    if _LABEL in frame:
        agg[_LABEL] = g[_LABEL].first()
    if _NOTES in frame:
        agg[_NOTES] = g[_NOTES].agg(
            lambda v: " | ".join(dict.fromkeys(str(t) for t in v.dropna() if str(t))))
    if _EXCL in frame:
        agg[_EXCL] = g[_EXCL].any()
    if _PART in frame:
        agg[_PART] = g[_PART].first()
    if _TARGET in frame:
        agg[_TARGET] = g[_TARGET].first()
    for col in s["hover"]:
        agg[col] = g[col].first()
    out = pd.DataFrame(agg)
    out.insert(0, _X, out.index.to_numpy())
    return out.reset_index(drop=True)


def _sortable(x: pd.Series) -> bool:
    return bool(pd.api.types.is_numeric_dtype(x) or pd.api.types.is_datetime64_any_dtype(x))


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(_X, kind="stable") if _sortable(frame[_X]) else frame


def _check_rates(chart: str, y: np.ndarray, n: np.ndarray) -> None:
    ok = np.isfinite(y) & np.isfinite(n)
    if np.any(ok & (n == 0) & (y > 0)):
        raise ValueError("Some points have events but a zero denominator (n = 0). Exclude "
                         "them (exclude=) or correct n=.")
    if np.any(ok & (y < 0)) or np.any(ok & (n < 0)):
        raise ValueError("y= and n= must be 0 or more on a chart of events over a denominator.")
    if chart in ("p", "pp") and np.any(ok & (y > n)):
        raise ValueError("On a p chart y= counts events out of n= cases, so y cannot exceed n.")


def _position(value: Any, k: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name}= is a 1-based point position (an integer), got {value!r}.")
    if not 1 <= int(value) < k:
        raise ValueError(f"{name}={value} must be between 1 and {k - 1} for {k} points.")
    return int(value)


def _excluded(pts: pd.DataFrame, exclude: Any, k: int) -> np.ndarray:
    out = np.zeros(k, dtype=bool)
    if _EXCL in pts:
        out |= pts[_EXCL].to_numpy(dtype=bool)
    elif exclude is not None and not isinstance(exclude, str):
        positions = [exclude] if isinstance(exclude, (int, np.integer)) else list(exclude)
        for p in positions:
            if isinstance(p, bool) or not isinstance(p, (int, np.integer)) or not 1 <= p <= k:
                raise ValueError(f"exclude= positions are 1-based integers up to {k}, got {p!r}.")
            out[int(p) - 1] = True
    return out


def _part_ends(pts: pd.DataFrame, part: Any, k: int) -> list[int]:
    """0-based end-exclusive boundaries: the index where each new part starts."""
    if part is None:
        return []
    if _PART in pts:
        v = pts[_PART].to_numpy()
        return [i for i in range(1, k) if v[i] != v[i - 1]]
    ends = [part] if isinstance(part, (int, np.integer)) else list(part)
    out = []
    for e in ends:
        if isinstance(e, bool) or not isinstance(e, (int, np.integer)) or not 1 <= e < k:
            raise ValueError(
                f"part= gives the point (1-based) where each part ends, between 1 and "
                f"{k - 1}; got {e!r}.")
        out.append(int(e))
    if out != sorted(set(out)):
        raise ValueError(f"part= positions must increase, got {ends!r}.")
    return out


def _part_labels(pts, part_id, part):
    if _PART in pts:
        return pts[_PART].to_numpy()
    return part_id


def _target(pts, target, k) -> np.ndarray | None:
    """The target line per point: a column or sequence of data, a number, or a sequence."""
    if _TARGET in pts:
        return pts[_TARGET].to_numpy(dtype=float)
    if target is None:
        return None
    if isinstance(target, (int, float)) and not isinstance(target, bool):
        return np.full(k, float(target))
    values = np.asarray(target, dtype=float)
    if len(values) != k:
        raise ValueError(f"target= has {len(values)} values for {k} points.")
    return values


def _variation(direction: np.ndarray, worse: str | None) -> np.ndarray:
    if worse is None:
        return np.where(direction == 0, "common", "neutral")
    bad = 1.0 if worse == "higher" else -1.0
    return np.where(direction == 0, "common",
                    np.where(direction == bad, "concerning", "improving"))


def _assurance(target, columns, worse) -> str | None:
    """
    Making Data Count's assurance: will the process meet its target? Read at the last
    point's limits: "pass" when the target lies beyond the limit on the bad side (the
    process cannot fail it by chance), "fail" beyond the limit on the good side, else
    "variable" (it will sometimes meet it and sometimes not).
    """
    if target is None or worse is None:
        return None
    t = float(np.asarray(target)[-1])
    upper, lower = float(columns["ucl"][-1]), float(columns["lcl"][-1])
    if not math.isfinite(t):
        return None
    if t > upper:
        return "pass" if worse == "higher" else "fail"
    if t < lower:
        return "fail" if worse == "higher" else "pass"
    return "variable"
