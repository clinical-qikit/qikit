"""
api.py — qic() main entry point, plus paretochart() and bchart().

    from qikit import qic
    result = qic(y=values, chart="i")
    result.plot()
    result.data
    result.signals
"""

from __future__ import annotations

import dataclasses
import math
import warnings
from typing import Any

import numpy as np
import pandas as pd

from .constants import c4
from .compute import compute
from .limits import CHARTS, VALID_CHARTS
from .options import PlotOptions, VALID_RUNS_HIGHLIGHT
from .results import BChartResult, ParetoResult, SPCResult
from .signals import _runs_signals, _sigma_signals

# ---------------------------------------------------------------------------
# qic() — main entry point
# ---------------------------------------------------------------------------

def qic(
    x: Any = None,
    y: Any = None,
    n: Any = None,
    data: pd.DataFrame | None = None,
    facets: str | None = None,
    notes: Any = None,
    chart: str = "run",
    agg_fun: str = "mean",
    method: str = "anhoej",
    multiply: float = 1.0,
    freeze: int | None = None,
    part: list[int] | int | str | None = None,
    exclude: list[int] | int | str | None = None,
    target: float | list[float] | str | None = None,
    cl: float | None = None,
    funnel: bool = False,
    # Layout
    nrow: int | None = None,
    ncol: int | None = None,
    scales: str = "fixed",
    # Labels
    title: str = "",
    ylab: str = "Value",
    xlab: str = "Subgroup",
    subtitle: str | None = None,
    caption: str | None = None,
    part_labels: list[str] | None = None,
    # Display toggles
    show_labels: bool = True,
    show_95: bool = False,
    show_grid: bool = False,
    show_x_labels: bool = True,
    # Formatting
    decimals: int = 1,
    point_size: float = 1.5,
    x_period: str | None = None,
    x_format: str | None = None,
    x_angle: int | None = None,
    x_pad: float = 1.0,
    x_order: list | str | None = None,
    y_expand: float | None = None,
    height: int | None = None,
    width: int | None = None,
    y_neg: bool = True,
    y_percent: bool | None = None,
    y_percent_accuracy: int | None = None,
    connect: bool | None = None,
    runs_highlight: str = "all",
    flip: bool = False,
    strip_horizontal: bool = False,
    print_summary: bool = False,
    _plot_options: PlotOptions | None = None,
) -> SPCResult:
    """
    Compute an SPC chart and return an SPCResult.

    Parameters
    ----------
    x      : x-axis values, or column name if data= supplied
    y      : numeric values, or column name if data= supplied
    n      : denominators for p/u/pp/up charts
    data   : optional DataFrame
    facets : column name to split into faceted subplots
    notes  : list of annotations, or column name
    chart  : chart type — run|i|mr|s|t|xbar|p|pp|c|u|up|g
    method : run-signal detection — anhoej (default), ihi, weco, nelson
    freeze : baseline ends at this index (1-based)
    part   : index (or list) where new phases begin (1-based), or column name
    exclude: index (or list) to ghost from baseline (1-based), or column name.
             Ghosted points are dropped from the limits *and* hidden from signal
             detection; freeze=/part= only narrow the baseline.
    cl     : user-supplied fixed center line
    multiply : multiply y values by this factor; note that y_percent=True (default
               for p/pp charts) already handles percent display — combining both
               will produce unexpectedly large values and raises a UserWarning
    funnel : when True, produces a funnel plot from a p/pp/u/up chart:
               sorts data by denominator (n) ascending, disables runs-signal
               detection (only sigma signals are meaningful cross-sectionally),
               and renders markers only with all x-axis labels shown.
               Valid only for charts with denominators (p, pp, u, up).
               notes=, a list-valued target= and exclude= are given in *input*
               order and are re-ordered along with the data; summary["excluded"]
               reports positions in the sorted (plotted) order. freeze= and
               part= are rejected — they assume the points are in time order.
    show_x_labels : when False, hide the x-axis tick labels while keeping the
               full label in the hover tooltip. Intended for funnel plots over
               hundreds of categorical units, where the axis text is unreadable
               anyway. Overridable per-call via result.plot(show_x_labels=...).
    connect : explicitly control point connectivity. True = lines+markers,
               False = markers only. When None (default), connectivity is
               inferred from the x-axis: categorical values that don't look
               sequential default to markers only.
    runs_highlight : which runs-signal points get colored orange on the chart.
               "all" (default) colors every point the runs method flagged — for
               the Anhoej crossings test that is the whole series. "localized"
               colors only the points forming an actual run, suppressing the
               crossings blanket. "none" turns off runs coloring entirely.
               Sigma outliers stay red in all three modes, and the crossings
               result is always reported in summary["crossings_signal"].
               Overridable per-call via result.plot(runs_highlight=...).

    Returns
    -------
    SPCResult (frozen dataclass)
    """
    chart = chart.lower().strip()

    # Default y_percent for proportion charts
    if y_percent is None:
        y_percent = chart in ("p", "pp")

    if y_percent and multiply != 1.0:
        warnings.warn(
            "y_percent=True already scales the axis to percent display. "
            "Setting multiply != 1 will produce unexpected results (e.g., 10% → 1000%). "
            "For p-charts, omit multiply= unless you intend to scale the raw proportion.",
            UserWarning,
            stacklevel=2,
        )

    if funnel and chart not in ("p", "pp", "u", "up"):
        raise ValueError(
            f"funnel=True is only valid for attribute charts with denominators "
            f"(p, pp, u, up). Got chart={chart!r}."
        )

    if funnel and (freeze is not None or part is not None):
        raise ValueError(
            "funnel=True cannot be combined with freeze= or part=. A funnel plot is a "
            "cross-sectional comparison ordered by denominator; freeze= and part= are "
            "temporal/phase concepts that assume the points are in time order."
        )

    if chart not in VALID_CHARTS:
        raise ValueError(
            f"Unknown chart type: {chart!r}. "
            f"Valid types: {sorted(VALID_CHARTS)}"
        )

    if runs_highlight not in VALID_RUNS_HIGHLIGHT:
        raise ValueError(
            f"runs_highlight must be one of {VALID_RUNS_HIGHLIGHT}, got {runs_highlight!r}."
        )

    # ------------------------------------------------------------------
    # Resolve spec early
    # ------------------------------------------------------------------
    chart_for_compute = "i" if chart == "t" else chart
    spec = CHARTS.get(chart_for_compute)

    # ------------------------------------------------------------------
    # Collect display params into one explicit dataclass
    # ------------------------------------------------------------------
    opts = _plot_options if _plot_options is not None else PlotOptions(
        show_labels=show_labels, show_95=show_95, show_grid=show_grid,
        show_x_labels=show_x_labels,
        decimals=decimals, point_size=point_size,
        x_angle=x_angle, x_pad=x_pad, x_period=x_period, x_format=x_format, x_order=x_order,
        y_neg=y_neg, y_percent=y_percent, y_percent_accuracy=y_percent_accuracy, y_expand=y_expand,
        flip=flip, strip_horizontal=strip_horizontal,
        nrow=nrow, ncol=ncol, scales=scales,
        part_labels=part_labels,
        height=height, width=width,
        connect=connect, runs_highlight=runs_highlight,
    )

    # ------------------------------------------------------------------
    # Facets: recursive call per facet value
    # ------------------------------------------------------------------
    if facets is not None:
        if data is None or not isinstance(data, pd.DataFrame):
            raise ValueError("facets= requires data= to be a DataFrame.")
        if not isinstance(facets, str) or facets not in data.columns:
            raise ValueError(f"facets= must be a column name string. Got {facets!r}.")

        # Warn if using list indices with facets
        if isinstance(part, (list, np.ndarray)) or isinstance(exclude, (list, np.ndarray)):
            warnings.warn(
                "Using integer indices for 'part' or 'exclude' with facets is risky as indices "
                "often differ per group. Using column names is recommended.",
                UserWarning
            )

        facet_vals = list(data[facets].unique())
        n_rows = len(data)

        sub_results = []
        for fv in facet_vals:
            facet_rows = np.flatnonzero((data[facets] == fv).to_numpy())
            sub_df = data[data[facets] == fv].copy()
            sub_result = qic(
                data=sub_df,
                x=x, y=y, n=n,
                chart=chart, method=method,
                freeze=freeze, part=part, exclude=exclude,
                cl=cl, multiply=multiply,
                title=str(fv), ylab=ylab, xlab=xlab,
                agg_fun=agg_fun,
                funnel=funnel,
                notes=_subset_per_facet(notes, facet_rows, n_rows),
                target=_subset_per_facet(target, facet_rows, n_rows),
                x_period=x_period,
                part_labels=part_labels,
                print_summary=False,
                _plot_options=opts,
            )
            sub_df_copy = sub_result.data.copy()
            sub_df_copy["facet"] = fv
            sub_results.append((fv, sub_result, sub_df_copy))

        combined_df = pd.concat([r[2] for r in sub_results], ignore_index=True)
        total_n_obs = sum(r[1].summary.get("n_obs", 0) for r in sub_results)
        total_n_baseline = sum(r[1].summary.get("n_baseline", 0) for r in sub_results)
        any_signals = any(r[1].signals for r in sub_results)
        by_facet = {str(r[0]): r[1].summary for r in sub_results}
        combined_summary: dict[str, Any] = {
            "n_obs": total_n_obs,
            "n_baseline": total_n_baseline,
            "signals": any_signals,
            "by_facet": by_facet,
        }

        facet_opts = dataclasses.replace(opts, part_indices=[])
        if funnel:
            facet_opts = dataclasses.replace(facet_opts, connect=False, x_nticks_all=True)
        plot_opts = dataclasses.asdict(facet_opts)

        return SPCResult(
            data=combined_df,
            chart_type=chart,
            method=method,
            summary=combined_summary,
            signals=any_signals,
            title=title,
            subtitle=subtitle,
            caption=caption,
            ylab=ylab,
            xlab=xlab,
            _plot_opts=plot_opts,
        )

    # ------------------------------------------------------------------
    # 1. Resolve and Aggregate Data
    # ------------------------------------------------------------------
    (
        x_vals, y_arr, n_vals, notes, part, exclude, part_labels,
        s_bar_val, sigma_hat_val, subgroup_n_val,
    ) = _resolve_and_aggregate(
        data, x, y, n, notes, part, exclude, part_labels, chart, agg_fun, x_period, spec
    )

    if len(y_arr) == 0:
        raise ValueError("y= contains no values.")

    # A bare index is accepted for exclude= just as it is for part=; normalising
    # here means the funnel remap and the baseline mask both see one shape.
    if isinstance(exclude, (int, np.integer)) and not isinstance(exclude, bool):
        exclude = [int(exclude)]

    # ------------------------------------------------------------------
    # 2. Funnel sort: order points by denominator ascending
    # ------------------------------------------------------------------
    if funnel:
        if n_vals is None:
            raise ValueError("funnel=True requires denominators (n=).")
        # Every per-point input must be permuted here. If a positional argument is
        # added to _assemble_final_df later, it belongs in this block too.
        sort_order = np.argsort(n_vals, kind="stable")
        x_vals = [x_vals[i] for i in sort_order]
        y_arr = y_arr[sort_order]
        n_vals = n_vals[sort_order]

        if isinstance(notes, (list, np.ndarray, pd.Series)) and len(notes) == len(sort_order):
            notes_vals = list(notes)
            notes = [notes_vals[i] for i in sort_order]

        if isinstance(target, (list, np.ndarray, pd.Series)) and len(target) == len(sort_order):
            target = np.asarray(target, dtype=float)[sort_order]

        if exclude is not None and not isinstance(exclude, str):
            # exclude is 1-based into the *input* order. new_pos[i] is where original
            # point i landed — the inverse of the sort permutation.
            new_pos = np.argsort(sort_order)
            exclude = [
                int(new_pos[i - 1]) + 1 if 1 <= i <= len(new_pos) else int(i)
                for i in exclude
            ]

    # ------------------------------------------------------------------
    # 3. Build baseline mask
    # ------------------------------------------------------------------
    n_pts_orig = len(y_arr)
    mask = np.ones(n_pts_orig, dtype=bool)
    exclude_mask = np.zeros(n_pts_orig, dtype=bool)

    if exclude:
        for idx in exclude:
            i = idx - 1
            if 0 <= i < n_pts_orig:
                mask[i] = False
                exclude_mask[i] = True

    if freeze is not None and part is not None:
        raise ValueError("Cannot use both freeze= and part= simultaneously.")

    freeze_idx: int | None = None
    if freeze is not None:
        freeze_idx = int(freeze)
        mask[freeze_idx:] = False

    part_indices: list[int] = []
    if part is not None:
        if isinstance(part, int):
            part_indices = [part]
        else:
            part_indices = [int(p) for p in part]

    # ------------------------------------------------------------------
    # 4. MR transform
    # ------------------------------------------------------------------
    if chart == "mr":
        if len(y_arr) < 2:
            raise ValueError("MR chart requires at least 2 data points.")
        y_arr = np.abs(np.diff(y_arr))
        x_vals = x_vals[1:]
        mask = mask[1:] & mask[:-1]
        exclude_mask = exclude_mask[1:] | exclude_mask[:-1]
        if part_indices:
            part_indices = [max(1, p - 1) for p in part_indices]
        n_vals = None

    n_pts = len(y_arr)

    # ------------------------------------------------------------------
    # 5. Validate & transform to proportion
    # ------------------------------------------------------------------
    if spec and spec.needs_n and n_vals is None:
        raise ValueError(f"Chart type {chart!r} requires denominators (n=).")

    if spec and spec.is_attribute:
        if n_vals is not None and np.any((n_vals == 0) & (y_arr > 0) & mask):
             raise ValueError(
                "Zero denominators found in the baseline with non-zero events. "
                "Exclude these points or supply non-zero denominators."
            )
        with np.errstate(divide="ignore", invalid="ignore"):
            y_arr = np.where(n_vals > 0, y_arr / n_vals, np.nan)

    # ------------------------------------------------------------------
    # 6. t chart transform
    # ------------------------------------------------------------------
    y_plot = y_arr
    if chart == "t":
        if np.any(y_arr[~np.isnan(y_arr)] < 0):
            raise ValueError("t chart requires non-negative values.")
        y_calc = np.where(np.isnan(y_arr), np.nan, y_arr ** (1.0 / 3.6))
    else:
        y_calc = y_arr

    # ------------------------------------------------------------------
    # 7. Compute limits and signals
    # ------------------------------------------------------------------
    (
        cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr, sigma_sig, runs_sig, runs_loc, runs_summary
    ) = _compute_spc_arrays(
        chart, chart_for_compute, y_calc, y_plot, n_vals, mask, cl, method,
        s_bar_val, sigma_hat_val, subgroup_n_val, part_indices, freeze_idx, spec,
        funnel=funnel, exclude_mask=exclude_mask,
    )

    # ------------------------------------------------------------------
    # 8. Assemble DataFrame
    # ------------------------------------------------------------------
    df = _assemble_final_df(
        x_vals, y_plot, cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr,
        sigma_sig, runs_sig, runs_loc, mask, notes, target, multiply, chart, part_indices, part_labels,
        exclude_mask=exclude_mask,
    )

    # ------------------------------------------------------------------
    # 9. Summary
    # ------------------------------------------------------------------
    any_signals = bool(np.any(sigma_sig) or np.any(runs_sig))
    exclude_list = [int(i + 1) for i in range(n_pts) if not mask[i]]
    if freeze_idx:
        exclude_list = [idx for idx in (exclude or [])]

    summary: dict[str, Any] = {
        "n_obs": int(np.sum(~np.isnan(df["y"]))),
        "n_baseline": int(np.sum(mask & ~np.isnan(df["y"]))),
        "signals": any_signals,
        "limit_basis": "baseline" if (freeze_idx or part_indices) else "all",
        "freeze": freeze_idx,
        "excluded": exclude_list,
        **runs_summary,
    }

    if print_summary:
        _print_summary(chart, summary)

    # ------------------------------------------------------------------
    # 10. Collect display params
    # ------------------------------------------------------------------
    opts = dataclasses.replace(opts, part_indices=part_indices, part_labels=part_labels)
    if funnel:
        opts = dataclasses.replace(opts, connect=False, x_nticks_all=True)
    plot_opts = dataclasses.asdict(opts)

    return SPCResult(
        data=df,
        chart_type=chart,
        method=method,
        summary=summary,
        signals=any_signals,
        title=title,
        subtitle=subtitle,
        caption=caption,
        ylab=ylab,
        xlab=xlab,
        _plot_opts=plot_opts,
    )


def _subset_per_facet(value, facet_rows: np.ndarray, n_rows: int):
    """
    Slice a positional per-row argument (notes=, target=) down to one facet.

    Column names and scalars are facet-independent and pass through untouched.
    A list is positional over data=, so it only makes sense to slice one whose
    length matches; anything else is left alone so the existing length error
    fires downstream rather than an IndexError here.
    """
    if isinstance(value, (list, np.ndarray, pd.Series)) and len(value) == n_rows:
        vals = list(value)
        return [vals[i] for i in facet_rows]
    return value


def _resolve_and_aggregate(
    data, x, y, n, notes, part, exclude, part_labels, chart, agg_fun, x_period, spec
) -> tuple:
    """Helper to resolve columns and aggregate data if needed."""
    s_bar_val = None
    sigma_hat_val = None
    subgroup_n_val = None
    n_vals = None

    if data is not None:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("data= must be a pandas DataFrame.")
        if not isinstance(y, str):
            raise ValueError("When data= is supplied, y= must be a column name string.")
        if y not in data.columns:
            raise ValueError(f"Column {y!r} not found in data.")

        y_col = y
        n_col = n if (n is not None and isinstance(n, str)) else None
        if n is not None and n_col is None:
             raise ValueError("When data= is supplied, n= must be a column name string.")
        if n_col and n_col not in data.columns:
            raise ValueError(f"Column {n_col!r} not found in data.")

        # Grouping
        if isinstance(x, str):
            if x not in data.columns:
                raise ValueError(f"Column {x!r} not found in data.")
            x_col = x

            if x_period is not None:
                if not pd.api.types.is_datetime64_any_dtype(data[x_col]):
                    data = data.copy()
                    data[x_col] = pd.to_datetime(data[x_col])
                period_map = {"day": "D", "week": "W", "month": "MS", "quarter": "QS", "year": "YS"}
                freq = period_map.get(x_period.lower(), x_period)
                grouped = data.groupby(pd.Grouper(key=x_col, freq=freq))
            else:
                grouped = data.groupby(x_col, sort=False)

            group_sizes = grouped[y_col].count()
            x_vals = list(group_sizes.index)

            if isinstance(notes, str) and notes in data.columns:
                notes = grouped[notes].apply(lambda x: " | ".join(x.dropna().unique().astype(str))).tolist()
            if isinstance(exclude, str) and exclude in data.columns:
                exclude = (np.where(grouped[exclude].any().values)[0] + 1).tolist()
            if isinstance(part, str) and part in data.columns:
                part_col_vals = grouped[part].first()
                if part_labels is None:
                    vals = part_col_vals.values
                    labels = [str(vals[0])]
                    for v_prev, v_curr in zip(vals[:-1], vals[1:]):
                        if v_prev != v_curr: labels.append(str(v_curr))
                    part_labels = labels
                changes = np.where(part_col_vals.values[1:] != part_col_vals.values[:-1])[0]
                part = (changes + 2).tolist()

            if chart in ("xbar", "s"):
                sizes = group_sizes.to_numpy()
                sds_arr = grouped[y_col].std(ddof=1).to_numpy(dtype=float)
                usable = (sizes >= 2) & ~np.isnan(sds_arr)
                if not np.any(usable):
                    largest = int(sizes.max()) if len(sizes) else 0
                    raise ValueError(
                        f"{chart} chart requires at least one subgroup with 2 or more "
                        f"observations; the largest has {largest}."
                    )
                s_bar_val, sigma_hat_val = _sigma_estimate(sizes, sds_arr, usable)
                y_arr = sds_arr if chart == "s" else _agg(grouped[y_col], agg_fun)
                n_vals = sizes.astype(float)
                # Scalar fallback for direct compute() callers only — n_vals above is
                # what actually drives the per-subgroup constants.
                subgroup_n_val = int(np.median(sizes))
            elif spec and spec.is_attribute:
                y_arr = grouped[y_col].sum().to_numpy(dtype=float)
                n_vals = grouped[n_col].sum().to_numpy(dtype=float) if n_col else None
            else:
                y_arr = _agg(grouped[y_col], agg_fun)
                n_vals = grouped[n_col].sum().to_numpy(dtype=float) if n_col else None
        else:
            # No implicit grouping
            if chart in ("xbar", "s"):
                raise ValueError(f"{chart} chart requires x= to be a column name string for subgroup grouping.")
            y_arr = data[y_col].to_numpy(dtype=float)
            x_vals = list(x) if x is not None else list(range(1, len(y_arr) + 1))
            n_vals = data[n_col].to_numpy(dtype=float) if n_col else None
            if isinstance(notes, str) and notes in data.columns: notes = data[notes].tolist()
            if isinstance(exclude, str) and exclude in data.columns:
                exclude = (np.where(data[exclude].values)[0] + 1).tolist()
            if isinstance(part, str) and part in data.columns:
                part_vals = data[part]
                if part_labels is None:
                    vals = part_vals.values
                    labels = [str(vals[0])]
                    for v_prev, v_curr in zip(vals[:-1], vals[1:]):
                        if v_prev != v_curr: labels.append(str(v_curr))
                    part_labels = labels
                changes = np.where(part_vals.values[1:] != part_vals.values[:-1])[0]
                part = (changes + 2).tolist()
    else:
        if chart in ("xbar", "s"):
            raise ValueError(f"{chart} chart requires data= as a DataFrame.")
        y_arr = np.asarray(y, dtype=float) if y is not None else np.array([])
        x_vals = list(x) if x is not None else list(range(1, len(y_arr) + 1))

        if len(x_vals) != len(y_arr):
            raise ValueError(f"Length of x ({len(x_vals)}) must match length of y ({len(y_arr)}).")

        n_vals = np.asarray(n, dtype=float) if n is not None else None

    return (
        x_vals, y_arr, n_vals, notes, part, exclude, part_labels,
        s_bar_val, sigma_hat_val, subgroup_n_val,
    )


def _sigma_estimate(
    sizes: np.ndarray, sds: np.ndarray, usable: np.ndarray
) -> tuple[float | None, float | None]:
    """
    Pick the σ estimator for an xbar/s chart. Returns (s_bar, sigma_hat); exactly
    one is non-None.

    Equal subgroup sizes get the classical S̄ = mean(sᵢ), which pairs with the
    A3/B3/B4 constants — those already embed the 1/c4(n) correction for the bias of
    an arithmetic mean of SDs.

    Unequal sizes get the pooled estimate σ̂ = Sp/c4(d+1), where
    Sp = √(Σ(nᵢ−1)sᵢ² / Σ(nᵢ−1)) and d = Σ(nᵢ−1)  (Montgomery 2019, §6.3.2).
    Feeding that into A3 would double-correct, so the limits functions switch to the
    3σ̂/√nᵢ form instead. Subgroups of size 1 contribute to neither estimate and get
    NaN limits.
    """
    if np.unique(sizes[usable]).size == 1:
        return float(np.mean(sds[usable])), None

    dof = sizes[usable] - 1.0
    total_dof = float(np.sum(dof))
    if total_dof <= 0:
        return np.nan, None
    pooled = math.sqrt(float(np.sum(dof * sds[usable] ** 2)) / total_dof)
    return None, pooled / c4(total_dof + 1.0)


def _agg(series_grouped, agg_fun):
    if agg_fun == "mean": return series_grouped.mean().to_numpy(dtype=float)
    if agg_fun == "median": return series_grouped.median().to_numpy(dtype=float)
    if agg_fun == "sum": return series_grouped.sum().to_numpy(dtype=float)
    raise ValueError(f"agg_fun must be 'mean', 'median', or 'sum', got {agg_fun!r}.")


def _compute_spc_arrays(
    chart, chart_for_compute, y_calc, y_plot, n_vals, mask, cl, method,
    s_bar_val, sigma_hat_val, subgroup_n_val, part_indices, freeze_idx, spec,
    funnel: bool = False, exclude_mask=None,
):
    n_pts = len(y_calc)
    if exclude_mask is None:
        exclude_mask = np.zeros(n_pts, dtype=bool)
    # t chart recomputes signals on the untransformed scale below; ghost the
    # same excluded points there rather than the baseline `mask` (which also
    # carries freeze/part boundaries that must still be signal-checked).
    y_plot_signal = np.where(exclude_mask, np.nan, y_plot)

    if part_indices and freeze_idx is None:
        boundaries = [0] + [p - 1 for p in part_indices] + [n_pts]
        cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr = [np.empty(n_pts) for _ in range(5)]
        sigma_sig, runs_sig, runs_loc = [np.zeros(n_pts, dtype=bool) for _ in range(3)]
        per_part_summaries = []
        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_mask = mask[start:end] # Preserve global exclusions in segments
            seg_raw = compute(
                chart=chart_for_compute, y=y_calc[start:end], n=n_vals[start:end] if n_vals is not None else None,
                mask=seg_mask, cl_override=cl, method=method, s_bar=s_bar_val,
                sigma_hat=sigma_hat_val, subgroup_n=subgroup_n_val,
                exclude_mask=exclude_mask[start:end],
            )
            cl_arr[start:end], ucl_arr[start:end], lcl_arr[start:end] = seg_raw["cl"], seg_raw["ucl"], seg_raw["lcl"]
            s3 = seg_raw["ucl"] - seg_raw["cl"]
            ucl_95_arr[start:end] = seg_raw["cl"] + s3 * (2/3)
            l95 = seg_raw["cl"] - s3 * (2/3)
            lcl_95_arr[start:end] = np.where(l95 < 0, 0.0, l95) if spec.floor_lcl else l95
            sigma_sig[start:end], runs_sig[start:end] = seg_raw["sigma_signal"], seg_raw["runs_signal"]
            runs_loc[start:end] = seg_raw["runs_signal_localized"]
            per_part_summaries.append({"part": seg_i + 1, **seg_raw["summary"]})

        runs_summary = {**per_part_summaries[-1], "parts": per_part_summaries}
        if chart == "t":
            cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr = [
                np.where(np.isnan(a), np.nan, np.where(a < 0, 0.0, a) ** 3.6)
                for a in [cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr]
            ]
            sigma_sig = _sigma_signals(y_plot_signal, ucl_arr, lcl_arr)
            new_summaries = []
            for seg_i in range(len(boundaries) - 1):
                s, e = boundaries[seg_i], boundaries[seg_i + 1]
                sig, loc, summ = _runs_signals(y_plot_signal[s:e], cl_arr[s:e], method=method)
                runs_sig[s:e], runs_loc[s:e] = sig, loc
                new_summaries.append({"part": seg_i + 1, **summ})
            runs_summary = {**new_summaries[-1], "parts": new_summaries}
    else:
        res = compute(
            chart_for_compute, y_calc, n_vals, mask, cl, subgroup_n_val, method, s_bar_val,
            sigma_hat=sigma_hat_val, exclude_mask=exclude_mask,
        )
        cl_arr, ucl_arr, lcl_arr = res["cl"], res["ucl"], res["lcl"]
        s3 = ucl_arr - cl_arr
        ucl_95_arr = cl_arr + s3 * (2/3)
        l95 = cl_arr - s3 * (2/3)
        lcl_95_arr = np.where(l95 < 0, 0.0, l95) if spec.floor_lcl else l95
        if chart == "t":
            cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr = [
                np.where(np.isnan(a), np.nan, np.where(a < 0, 0.0, a) ** 3.6)
                for a in [cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr]
            ]
            sigma_sig = _sigma_signals(y_plot_signal, ucl_arr, lcl_arr)
            runs_sig, runs_loc, runs_summary = _runs_signals(y_plot_signal, cl_arr, method=method)
        else:
            sigma_sig, runs_sig, runs_summary = res["sigma_signal"], res["runs_signal"], res["summary"]
            runs_loc = res["runs_signal_localized"]

    if funnel:
        # Runs rules assume temporal ordering; suppress them for cross-sectional funnel plots.
        runs_sig = np.zeros(len(runs_sig), dtype=bool)
        runs_loc = np.zeros(len(runs_loc), dtype=bool)
        runs_summary = {**runs_summary, "runs_disabled": True, "note": "runs signals suppressed (funnel mode)"}

    return cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr, sigma_sig, runs_sig, runs_loc, runs_summary


def _assemble_final_df(
    x_vals, y_plot, cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr,
    sigma_sig, runs_sig, runs_loc, mask, notes, target, multiply, chart, part_indices, part_labels,
    exclude_mask=None,
):
    if multiply != 1.0:
        y_plot, cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr = [
            a * multiply for a in [y_plot, cl_arr, ucl_arr, lcl_arr, ucl_95_arr, lcl_95_arr]
        ]

    if exclude_mask is None:
        exclude_mask = np.zeros(len(y_plot), dtype=bool)

    df_dict = {
        "x": x_vals, "y": y_plot, "cl": cl_arr, "ucl": ucl_arr, "lcl": lcl_arr,
        "ucl_95": ucl_95_arr, "lcl_95": lcl_95_arr,
        "sigma_signal": sigma_sig, "runs_signal": runs_sig,
        "runs_signal_localized": runs_loc, "baseline": mask,
        "excluded": exclude_mask,
    }

    if notes is not None:
        if isinstance(notes, (list, np.ndarray, pd.Series)): notes_vals = list(notes)
        else: notes_vals = [str(notes)] * len(x_vals)
        if chart == "mr": notes_vals = notes_vals[1:]

        if len(notes_vals) != len(x_vals):
            raise ValueError(f"Length of notes ({len(notes_vals)}) must match length of x-axis ({len(x_vals)}).")

        df_dict["notes"] = ["" if (v is None or (isinstance(v, float) and np.isnan(v))) else str(v) for v in notes_vals]

    if target is not None:
        if isinstance(target, (list, np.ndarray, pd.Series)):
            t_vals = np.asarray(target, dtype=float)
            if chart == "mr": t_vals = t_vals[1:]
        else: t_vals = np.full(len(x_vals), float(target))
        df_dict["target"] = t_vals * multiply if multiply != 1.0 else t_vals

    if part_indices:
        n_pts = len(y_plot)
        boundaries = [0] + [p - 1 for p in part_indices] + [n_pts]
        part_col = np.empty(n_pts, dtype=int)
        for i in range(len(boundaries) - 1):
            part_col[boundaries[i]:boundaries[i+1]] = i + 1
        if part_labels and len(part_labels) == (len(boundaries) - 1):
            df_dict["part"] = [part_labels[i-1] for i in part_col]
        else:
            df_dict["part"] = part_col

    return pd.DataFrame(df_dict)


def _print_summary(chart: str, summary: dict[str, Any]) -> None:
    print(f"\nChart: {chart.upper()}")
    print(f"  n observations : {summary['n_obs']}")
    print(f"  n baseline     : {summary['n_baseline']}")
    print(f"  Signals        : {'YES' if summary['signals'] else 'none'}")
    if "weco_rules_triggered" in summary: print(f"  WECO Rules     : {summary['weco_rules_triggered']}")
    if "nelson_rules_triggered" in summary: print(f"  Nelson Rules   : {summary['nelson_rules_triggered']}")
    if "longest_run" in summary:
        print(f"  Longest run    : {summary['longest_run']} (threshold: {summary['run_threshold']})")
        print(f"  Crossings      : {summary['n_crossings']} (threshold: {summary['crossings_threshold']})")


def paretochart(
    x: Any, data: pd.DataFrame | None = None, title: str = "", subtitle: str | None = None,
    caption: str | None = None, ylab: str = "Frequency", xlab: str = "", use_na: bool = False, x_angle: int | None = None,
) -> ParetoResult:
    """Compute a Pareto chart."""
    vals = data[x] if (data is not None and isinstance(x, str)) else pd.Series(x)
    counts = vals.value_counts(dropna=not use_na).sort_values(ascending=False)
    df = counts.reset_index()
    df.columns = ["category", "count"]
    df["cum_sum"] = df["count"].cumsum()
    df["cum_percent"] = (df["cum_sum"] / df["count"].sum()) * 100
    return ParetoResult(df, title, subtitle, caption, ylab, xlab, {"x_angle": x_angle})


def bchart(
    x: Any, target: float | int | None = None, or_ratio: float = 2.0, limit: float = 3.5,
    title: str = "", subtitle: str | None = None, caption: str | None = None, ylab: str = "CUSUM", xlab: str = "Case #",
) -> BChartResult:
    """Compute a Bernoulli CUSUM chart for binary data."""
    x_arr = np.asarray(x, dtype=float)
    n = len(x_arr)
    if target is None: p0 = float(np.nanmean(x_arr))
    elif target > 1: p0 = float(np.nanmean(x_arr[:int(target)]))
    else: p0 = float(target)
    if not (0 < p0 < 1): raise ValueError("Target (baseline risk) must be between 0 and 1.")
    def getp(p, o): return (p * o) / (1 - p + p * o)
    p1, p2 = getp(p0, or_ratio), getp(p0, 1.0 / or_ratio)
    with np.errstate(divide="ignore", invalid="ignore"):
        s1 = x_arr * np.log(p1 / p0) + (1 - x_arr) * np.log((1 - p1) / (1 - p0))
        s2 = x_arr * np.log(p2 / p0) + (1 - x_arr) * np.log((1 - p2) / (1 - p0))
    c1, c2, sig1, sig2 = np.zeros(n), np.zeros(n), np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    z1, z2, l2 = 0.0, 0.0, -limit
    for i in range(n):
        if np.isnan(s1[i]): c1[i], c2[i] = z1, z2; continue
        z1i = z1 + s1[i]; sig1[i] = (z1i >= limit); c1[i] = z1i * (z1i > 0) * (z1i <= limit); z1 = c1[i]
        z2i = z2 - s2[i]; sig2[i] = (z2i <= l2); c2[i] = z2i * (z2i < 0) * (z2i >= l2); z2 = c2[i]
    df = pd.DataFrame({"x": np.arange(1, n + 1), "y": x_arr, "cusum_up": c1, "cusum_down": c2, "signal_up": sig1, "signal_down": sig2, "limit": limit})
    return BChartResult(df, p0, or_ratio, limit, title or f"Bernoulli CUSUM (p0={p0:.3f}, OR={or_ratio})", subtitle, caption, ylab, xlab)
