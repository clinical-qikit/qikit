"""
qikit — SPC charts and quality improvement tools for healthcare.

One function. One result object. One .plot() call.

    from qikit import qic
    result = qic(y=values, chart="i")
    result.plot()
    result.data
    result.signals

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022. ISBN 978-1-119-69013-9, 978-1-119-69012-2.
3. Anhoej J, Olesen AV. Run charts revisited. PLoS ONE 9(11), 2014.
4. Anhoej J. Diagnostic value of run chart analysis. PLoS ONE 10(3), 2015.
5. Laney DB. Improved control charts for attributes. Quality Engineering 14(4), 2002.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from qikit import core as _core

__version__ = "0.1.0a0"
__all__ = ["SPCResult", "qic", "__version__"]


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SPCResult:
    """
    Immutable result of a qic() call.

    Fields
    ------
    data       : DataFrame with columns x, y, cl, ucl, lcl, sigma_signal,
                 runs_signal, baseline
    chart_type : "run", "i", "mr", "p", "u", "c", etc.
    method     : run-signal detection method ("anhoej")
    summary    : audit dict — n_obs, longest_run, n_crossings, thresholds, etc.
    signals    : True if any non-random variation detected
    title      : chart title
    ylab       : y-axis label
    xlab       : x-axis label
    """

    data: pd.DataFrame
    chart_type: str
    method: str
    summary: dict[str, Any]
    signals: bool
    title: str
    ylab: str
    xlab: str
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        """Render as a Plotly Figure. Keyword args override stored display options."""
        from qikit.render import plot_result

        opts = {**self._plot_opts, **overrides}
        return plot_result(self, **opts)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to a plain dict suitable for JSON, MCP, or API responses.
        NaN values become None (JSON-safe).
        """
        def _safe(v: Any) -> Any:
            if isinstance(v, float) and np.isnan(v):
                return None
            if isinstance(v, np.bool_):
                return bool(v)
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, np.floating):
                return None if np.isnan(v) else float(v)
            return v

        rows = []
        for _, row in self.data.iterrows():
            rows.append({k: _safe(v) for k, v in row.items()})

        return {
            "chart_type": self.chart_type,
            "method": self.method,
            "signals": self.signals,
            "title": self.title,
            "ylab": self.ylab,
            "xlab": self.xlab,
            "summary": {k: _safe(v) for k, v in self.summary.items()},
            "data": rows,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        n = len(self.data)
        sig = "SIGNAL" if self.signals else "no signal"
        return f"SPCResult(chart={self.chart_type!r}, n={n}, {sig})"


# ---------------------------------------------------------------------------
# qic() — main entry point
# ---------------------------------------------------------------------------

# Display-only params that travel with the result via _plot_opts
_PLOT_OPT_KEYS = frozenset({
    "show_labels", "show_95", "show_grid",
    "decimals", "point_size",
    "x_angle", "x_pad", "x_period", "x_format",
    "y_neg", "y_percent", "y_percent_accuracy", "y_expand",
    "flip", "strip_horizontal",
    "nrow", "ncol", "scales",
    "part_labels", "part_indices",
})


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
    part: list[int] | int | None = None,
    exclude: list[int] | None = None,
    target: float | None = None,
    cl: float | None = None,
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
    # Formatting
    decimals: int = 1,
    point_size: float = 1.5,
    x_period: str | None = None,
    x_format: str | None = None,
    x_angle: int | None = None,
    x_pad: float = 1.0,
    y_expand: float | None = None,
    y_neg: bool = True,
    y_percent: bool = False,
    y_percent_accuracy: int | None = None,
    flip: bool = False,
    strip_horizontal: bool = False,
    print_summary: bool = False,
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
    notes  : list of annotations aligned to data points
    chart  : chart type — run|i|mr|s|t|xbar|p|pp|c|u|up|g
    method : run-signal detection — anhoej (default)
    freeze : baseline ends at this index (1-based)
    part   : index (or list) where new phases begin (1-based)
    exclude: list of indices to ghost from calculations (1-based)
    cl     : user-supplied fixed center line
    multiply : multiply y values by this factor

    Returns
    -------
    SPCResult (frozen dataclass)
    """
    chart = chart.lower().strip()

    if chart not in _core.VALID_CHARTS:
        raise ValueError(
            f"Unknown chart type: {chart!r}. "
            f"Valid types: {sorted(_core.VALID_CHARTS)}"
        )

    # ------------------------------------------------------------------
    # Facets: recursive call per facet value
    # ------------------------------------------------------------------
    if facets is not None:
        if data is None or not isinstance(data, pd.DataFrame):
            raise ValueError("facets= requires data= to be a DataFrame.")
        if not isinstance(facets, str) or facets not in data.columns:
            raise ValueError(f"facets= must be a column name string. Got {facets!r}.")

        facet_vals = list(data[facets].unique())

        # Build display opts to pass through (excluding facets itself)
        display_kwargs: dict[str, Any] = {
            "nrow": nrow, "ncol": ncol, "scales": scales,
            "show_labels": show_labels, "show_95": show_95, "show_grid": show_grid,
            "decimals": decimals, "point_size": point_size,
            "x_angle": x_angle, "x_pad": x_pad, "x_period": x_period,
            "x_format": x_format, "y_expand": y_expand, "y_neg": y_neg,
            "y_percent": y_percent, "y_percent_accuracy": y_percent_accuracy,
            "flip": flip, "strip_horizontal": strip_horizontal,
            "part_labels": part_labels,
        }

        sub_results = []
        for fv in facet_vals:
            sub_df = data[data[facets] == fv].copy()
            sub_result = qic(
                data=sub_df,
                x=x, y=y, n=n,
                chart=chart, method=method,
                freeze=freeze, part=part, exclude=exclude,
                cl=cl, multiply=multiply,
                title=str(fv), ylab=ylab, xlab=xlab,
                agg_fun=agg_fun,
                print_summary=False,
                **display_kwargs,
            )
            sub_df_copy = sub_result.data.copy()
            sub_df_copy["facet"] = fv
            sub_results.append((fv, sub_result, sub_df_copy))

        combined_df = pd.concat([r[2] for r in sub_results], ignore_index=True)
        total_n_obs = sum(r[1].summary.get("n_obs", 0) for r in sub_results)
        any_signals = any(r[1].signals for r in sub_results)
        by_facet = {str(r[0]): r[1].summary for r in sub_results}
        combined_summary: dict[str, Any] = {
            "n_obs": total_n_obs,
            "signals": any_signals,
            "by_facet": by_facet,
        }

        local_vars = locals()
        plot_opts: dict[str, Any] = {k: local_vars[k] for k in _PLOT_OPT_KEYS if k in local_vars}
        plot_opts["part_indices"] = []

        return SPCResult(
            data=combined_df,
            chart_type=chart,
            method=method,
            summary=combined_summary,
            signals=any_signals,
            title=title,
            ylab=ylab,
            xlab=xlab,
            _plot_opts=plot_opts,
        )

    # ------------------------------------------------------------------
    # 1. Resolve values from DataFrame and Aggregate
    # ------------------------------------------------------------------

    s_bar_val: float | None = None
    subgroup_n_val: int | None = None

    if data is not None:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("data= must be a pandas DataFrame.")
        if not isinstance(y, str):
            raise ValueError("When data= is supplied, y= must be a column name string.")
        if y not in data.columns:
            raise ValueError(f"Column {y!r} not found in data.")
            
        y_col = y
        
        n_col: str | None = None
        if n is not None:
            if not isinstance(n, str):
                raise ValueError("When data= is supplied, n= must be a column name string.")
            if n not in data.columns:
                raise ValueError(f"Column {n!r} not found in data.")
            n_col = n
            
        # Grouping happens if x is a column name (or if it's implicitly grouped)
        if isinstance(x, str):
            if x not in data.columns:
                raise ValueError(f"Column {x!r} not found in data.")
            x_col = x
            
            if x_period is not None:
                # Convert to datetime if it isn't already
                if not pd.api.types.is_datetime64_any_dtype(data[x_col]):
                    data = data.copy()
                    data[x_col] = pd.to_datetime(data[x_col])
                    
                # Map qicharts2 friendly periods to pandas offset aliases
                period_map = {
                    "day": "D",
                    "week": "W",       # Week ending Sunday
                    "month": "MS",     # Month start
                    "quarter": "QS",   # Quarter start
                    "year": "YS",      # Year start
                }
                freq = period_map.get(x_period.lower(), x_period)
                grouped = data.groupby(pd.Grouper(key=x_col, freq=freq))
            else:
                grouped = data.groupby(x_col, sort=False)
                
            # Use the index of the aggregated series to capture empty periods correctly
            group_sizes = grouped[y_col].count()
            x_vals = list(group_sizes.index)
            
            if chart in ("xbar", "s"):
                subgroup_n_val = int(np.median(group_sizes.to_numpy()))
                group_sds = grouped[y_col].std(ddof=1)
                
                if chart == "xbar" and subgroup_n_val not in _core.A3:
                    raise ValueError(f"xbar chart requires subgroup_n in 2..25, got {subgroup_n_val}.")
                if chart == "s" and subgroup_n_val not in _core.B4:
                    raise ValueError(f"s chart requires subgroup_n in 2..25, got {subgroup_n_val}.")
                    
                sds_arr = group_sds.to_numpy(dtype=float)
                valid_sds = sds_arr[~np.isnan(sds_arr)]
                s_bar_val = float(np.mean(valid_sds)) if len(valid_sds) > 0 else np.nan
                
                if chart == "s":
                    y_arr = sds_arr
                else:
                    if agg_fun == "mean":
                        y_arr = grouped[y_col].mean().to_numpy(dtype=float)
                    elif agg_fun == "median":
                        y_arr = grouped[y_col].median().to_numpy(dtype=float)
                    elif agg_fun == "sum":
                        y_arr = grouped[y_col].sum().to_numpy(dtype=float)
                    else:
                        raise ValueError(f"agg_fun must be 'mean', 'median', or 'sum', got {agg_fun!r}.")
                n_vals = None
                
            elif chart in ("p", "u", "pp", "up", "ip"):
                # Attribute charts always sum their numerators and denominators
                y_arr = grouped[y_col].sum().to_numpy(dtype=float)
                if n_col:
                    n_vals = grouped[n_col].sum().to_numpy(dtype=float)
                else:
                    n_vals = None
                    
            else:
                # Other charts (run, i, mr, c, g, t) use agg_fun
                if agg_fun == "mean":
                    y_arr = grouped[y_col].mean().to_numpy(dtype=float)
                elif agg_fun == "median":
                    y_arr = grouped[y_col].median().to_numpy(dtype=float)
                elif agg_fun == "sum":
                    y_arr = grouped[y_col].sum().to_numpy(dtype=float)
                else:
                    raise ValueError(f"agg_fun must be 'mean', 'median', or 'sum', got {agg_fun!r}.")
                
                if n_col:
                    n_vals = grouped[n_col].sum().to_numpy(dtype=float)
                else:
                    n_vals = None

        else:
            # Dataframe provided, but no grouping requested (x is list/None)
            if chart in ("xbar", "s"):
                raise ValueError(f"{chart} chart requires x= to be a column name string for subgroup grouping.")
                
            y_arr = data[y_col].to_numpy(dtype=float)
            if x is None:
                x_vals = list(range(1, len(y_arr) + 1))
            else:
                x_vals = list(x)
                
            if n_col:
                n_vals = data[n_col].to_numpy(dtype=float)
            else:
                n_vals = None

    else:
        # No DataFrame provided
        if chart in ("xbar", "s"):
            raise ValueError(f"{chart} chart requires data= as a DataFrame with x= as a grouping column.")
            
        if y is None:
            raise ValueError("y= is required.")
        y_arr = np.asarray(y, dtype=float)
        x_vals = list(x) if x is not None else list(range(1, len(y_arr) + 1))
        n_vals = np.asarray(n, dtype=float) if n is not None else None

    if len(y_arr) == 0:
        raise ValueError("y= contains no values.")

    # ------------------------------------------------------------------
    # 2. Apply multiply
    # ------------------------------------------------------------------
    if multiply != 1.0:
        y_arr = y_arr * multiply

    # ------------------------------------------------------------------
    # 3. Build baseline mask (on original points)
    # ------------------------------------------------------------------
    n_pts_orig = len(y_arr)
    mask = np.ones(n_pts_orig, dtype=bool)

    if exclude:
        for idx in exclude:
            i = idx - 1
            if 0 <= i < n_pts_orig:
                mask[i] = False

    # Check for conflicting freeze + part
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
        # For multi-part mode, we do NOT mask out — per-segment loop handles it

    # ------------------------------------------------------------------
    # 4. MR transform: y → moving ranges
    # ------------------------------------------------------------------
    if chart == "mr":
        if len(y_arr) < 2:
            raise ValueError("MR chart requires at least 2 data points.")
        y_arr = np.abs(np.diff(y_arr))
        x_vals = x_vals[1:]  # MR labeled by second point in each pair
        # A moving range is valid only if both adjacent points are valid
        mask = mask[1:] & mask[:-1]
        # n is not applicable for MR charts
        n_vals = None

    n_pts = len(y_arr)

    # ------------------------------------------------------------------
    # 5. Validate denominators & transform to proportion/rate
    # ------------------------------------------------------------------
    chart_for_compute = chart
    if chart == "t":
        chart_for_compute = "i"

    spec = _core.CHARTS.get(chart_for_compute)
    if spec and spec.needs_n and n_vals is None:
        raise ValueError(f"Chart type {chart!r} requires denominators (n=).")

    if chart in ("p", "u", "pp", "up", "ip"):
        # Explicit validation for raw counts before transformation:
        # If the denominator is 0, but the numerator > 0, the data is invalid.
        # (If both are 0, it gracefully becomes NaN).
        if n_vals is not None and np.any((n_vals == 0) & (y_arr > 0) & mask):
             raise ValueError(
                "Zero denominators found in the baseline with non-zero events. "
                "Exclude these points or supply non-zero denominators."
            )

        with np.errstate(divide="ignore", invalid="ignore"):
            # If n_vals > 0 compute proportion; else NaN
            y_arr = np.where(n_vals > 0, y_arr / n_vals, np.nan)

    # ------------------------------------------------------------------
    # 6. t chart: power transform
    # ------------------------------------------------------------------
    y_plot = y_arr  # values to display on the chart
    if chart == "t":
        if np.any(y_arr[~np.isnan(y_arr)] < 0):
            raise ValueError("t chart requires non-negative values.")
        y_calc = np.where(np.isnan(y_arr), np.nan, y_arr ** (1.0 / 3.6))
    else:
        y_calc = y_arr

    # ------------------------------------------------------------------
    # 7. Compute limits and signals
    # ------------------------------------------------------------------

    if part_indices and freeze_idx is None:
        # Multi-part: independent computation per segment
        boundaries = [0] + [p - 1 for p in part_indices] + [n_pts]
        cl_arr = np.empty(n_pts)
        ucl_arr = np.empty(n_pts)
        lcl_arr = np.empty(n_pts)
        ucl_95_arr = np.empty(n_pts)
        lcl_95_arr = np.empty(n_pts)
        sigma_sig = np.zeros(n_pts, dtype=bool)
        runs_sig = np.zeros(n_pts, dtype=bool)
        per_part_summaries = []

        for seg_i in range(len(boundaries) - 1):
            start, end = boundaries[seg_i], boundaries[seg_i + 1]
            seg_y = y_calc[start:end]
            seg_n = n_vals[start:end] if n_vals is not None else None
            seg_mask = np.ones(end - start, dtype=bool)
            # Apply exclude within this segment (1-based indices relative to full array)
            if exclude:
                for idx in exclude:
                    i = idx - 1 - start
                    if 0 <= i < end - start:
                        seg_mask[i] = False
            seg_raw = _core.compute(
                chart=chart_for_compute,
                y=seg_y, n=seg_n, mask=seg_mask,
                cl_override=cl, method=method,
                s_bar=s_bar_val, subgroup_n=subgroup_n_val,
            )
            cl_arr[start:end] = seg_raw["cl"]
            ucl_arr[start:end] = seg_raw["ucl"]
            lcl_arr[start:end] = seg_raw["lcl"]

            sigma_3 = seg_raw["ucl"] - seg_raw["cl"]
            u_95 = seg_raw["cl"] + sigma_3 * (2.0 / 3.0)
            l_95 = seg_raw["cl"] - sigma_3 * (2.0 / 3.0)
            if spec and spec.floor_lcl:
                l_95 = np.where(l_95 < 0, 0.0, l_95)
            ucl_95_arr[start:end] = u_95
            lcl_95_arr[start:end] = l_95

            sigma_sig[start:end] = seg_raw["sigma_signal"]
            runs_sig[start:end] = seg_raw["runs_signal"]
            per_part_summaries.append({"part": seg_i + 1, **seg_raw["summary"]})

        runs_summary = {**per_part_summaries[-1]}  # last part is "current"
        runs_summary["parts"] = per_part_summaries

        # Back-transform for t chart
        if chart == "t":
            cl_arr = np.where(np.isnan(cl_arr), np.nan, cl_arr ** 3.6)
            ucl_arr = np.where(np.isnan(ucl_arr), np.nan, ucl_arr ** 3.6)
            lcl_arr = np.where(np.isnan(lcl_arr), np.nan, np.where(lcl_arr < 0, 0.0, lcl_arr ** 3.6))
            ucl_95_arr = np.where(np.isnan(ucl_95_arr), np.nan, ucl_95_arr ** 3.6)
            lcl_95_arr = np.where(np.isnan(lcl_95_arr), np.nan, np.where(lcl_95_arr < 0, 0.0, lcl_95_arr ** 3.6))
            sigma_sig = _core._sigma_signals(y_plot, ucl_arr, lcl_arr)
            runs_result_arr = np.zeros(n_pts, dtype=bool)
            new_summaries = []
            for seg_i in range(len(boundaries) - 1):
                start, end = boundaries[seg_i], boundaries[seg_i + 1]
                seg_cl = cl_arr[start:end]
                seg_runs, seg_runs_summary = _core._runs_signals(
                    y_plot[start:end], seg_cl, method=method
                )
                runs_result_arr[start:end] = seg_runs
                new_summaries.append({"part": seg_i + 1, **seg_runs_summary})
            runs_sig = runs_result_arr
            runs_summary = {**new_summaries[-1]}
            runs_summary["parts"] = new_summaries

    else:
        result_raw = _core.compute(
            chart=chart_for_compute,
            y=y_calc,
            n=n_vals,
            mask=mask,
            cl_override=cl,
            method=method,
            s_bar=s_bar_val,
            subgroup_n=subgroup_n_val,
        )

        cl_arr = result_raw["cl"]
        ucl_arr = result_raw["ucl"]
        lcl_arr = result_raw["lcl"]

        sigma_3 = ucl_arr - cl_arr
        ucl_95_arr = cl_arr + sigma_3 * (2.0 / 3.0)
        lcl_95_arr = cl_arr - sigma_3 * (2.0 / 3.0)
        if spec and spec.floor_lcl:
            lcl_95_arr = np.where(lcl_95_arr < 0, 0.0, lcl_95_arr)

        # Back-transform for t chart
        if chart == "t":
            cl_arr = np.where(np.isnan(cl_arr), np.nan, cl_arr ** 3.6)
            ucl_arr = np.where(np.isnan(ucl_arr), np.nan, ucl_arr ** 3.6)
            lcl_arr = np.where(np.isnan(lcl_arr), np.nan, np.where(lcl_arr < 0, 0.0, lcl_arr ** 3.6))
            ucl_95_arr = np.where(np.isnan(ucl_95_arr), np.nan, ucl_95_arr ** 3.6)
            lcl_95_arr = np.where(np.isnan(lcl_95_arr), np.nan, np.where(lcl_95_arr < 0, 0.0, lcl_95_arr ** 3.6))
            # Signals computed on original scale against back-transformed limits
            sigma_sig = _core._sigma_signals(y_plot, ucl_arr, lcl_arr)
            runs_sig, runs_summary = _core._runs_signals(y_plot, cl_arr, method=method)
        else:
            sigma_sig = result_raw["sigma_signal"]
            runs_sig = result_raw["runs_signal"]
            runs_summary = result_raw["summary"]

    # ------------------------------------------------------------------
    # 8. Assemble DataFrame (consistent schema: ucl/lcl always present)
    # ------------------------------------------------------------------
    df_dict: dict[str, Any] = {
        "x": x_vals,
        "y": y_plot,
        "cl": cl_arr,
        "ucl": ucl_arr,
        "lcl": lcl_arr,
        "ucl_95": ucl_95_arr,
        "lcl_95": lcl_95_arr,
        "sigma_signal": sigma_sig,
        "runs_signal": runs_sig,
        "baseline": mask,
    }

    if notes is not None:
        if isinstance(notes, str) and data is not None and notes in data.columns:
            notes_vals = data[notes].tolist()
        else:
            notes_vals = list(notes)
            
        if chart == "mr":
            notes_vals = notes_vals[1:]
        
        if len(notes_vals) != len(x_vals):
            raise ValueError(f"Length of notes ({len(notes_vals)}) must match length of x-axis ({len(x_vals)}).")
        
        df_dict["notes"] = notes_vals

    if target is not None:
        if isinstance(target, (list, np.ndarray, pd.Series)):
            target_vals = np.asarray(target, dtype=float)
            if chart == "mr":
                target_vals = target_vals[1:]
            if len(target_vals) != len(x_vals):
                raise ValueError(f"Length of target array ({len(target_vals)}) must match length of x-axis ({len(x_vals)}).")
        else:
            target_vals = np.full(len(x_vals), float(target))
        df_dict["target"] = target_vals

    # Add part column if multi-part
    if part_indices:
        boundaries_for_col = [0] + [p - 1 for p in part_indices] + [n_pts]
        part_col = np.empty(n_pts, dtype=int)
        for seg_i in range(len(boundaries_for_col) - 1):
            start, end = boundaries_for_col[seg_i], boundaries_for_col[seg_i + 1]
            part_col[start:end] = seg_i + 1
        df_dict["part"] = part_col

    df = pd.DataFrame(df_dict)

    # Add notes column if provided
    if notes is not None:
        notes_arr = list(notes)
        expected_len = n_pts
        if len(notes_arr) != expected_len:
            raise ValueError(
                f"notes= length ({len(notes_arr)}) must match number of data points ({expected_len})."
            )
        df["note"] = [
            "" if (v is None or (isinstance(v, float) and np.isnan(v))) else str(v)
            for v in notes_arr
        ]

    # ------------------------------------------------------------------
    # 9. Summary
    # ------------------------------------------------------------------
    any_signals = bool(np.any(sigma_sig) or np.any(runs_sig))

    exclude_list = [int(i + 1) for i in range(n_pts) if not mask[i]]
    if freeze_idx:
        # Don't list frozen-out points as "excluded" — they're just after freeze
        exclude_list = [idx for idx in (exclude or [])]

    summary: dict[str, Any] = {
        "n_obs": int(np.sum(~np.isnan(y_plot))),
        "n_baseline": int(np.sum(mask & ~np.isnan(y_plot))),
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
    local_vars = locals()
    plot_opts = {k: local_vars[k] for k in _PLOT_OPT_KEYS if k in local_vars}
    plot_opts["part_indices"] = part_indices  # list computed earlier

    return SPCResult(
        data=df,
        chart_type=chart,
        method=method,
        summary=summary,
        signals=any_signals,
        title=title,
        ylab=ylab,
        xlab=xlab,
        _plot_opts=plot_opts,
    )


def _print_summary(chart: str, summary: dict[str, Any]) -> None:
    print(f"\nChart: {chart.upper()}")
    print(f"  n observations : {summary['n_obs']}")
    print(f"  n baseline     : {summary['n_baseline']}")
    print(f"  Signals        : {'YES' if summary['signals'] else 'none'}")
    if "longest_run" in summary:
        print(
            f"  Longest run    : {summary['longest_run']} "
            f"(threshold: {summary['run_threshold']})"
        )
        print(
            f"  Crossings      : {summary['n_crossings']} "
            f"(threshold: {summary['crossings_threshold']})"
        )
