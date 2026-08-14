"""
spc_plots.py — Plotly rendering for SPCResult.

Design principles (Tufte, Visual Display of Quantitative Information):
- Maximize data-ink ratio; every pixel earns its place
- No plot border, no background fill, no y spine, minimal grid
- The series carries the darkest ink; reference lines are light hairlines
- Signal points: the only color — brick (sigma), amber (runs) — plus a
  diamond symbol on runs points so the distinction survives colorblindness
- Signal points are drawn larger than routine points
- CL/UCL/LCL labeled directly at right edge; no legend
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from qikit.spc.options import VALID_RUNS_HIGHLIGHT

from .utils import (
    apply_tufte_theme,
    NORMAL, CL, LIMIT, SIGMA, RUNS, TARGET, GRID, WARN, AXIS,
    TEXT, TEXT_MUTED, TEXT_FAINT,
)


def _resolve_runs_signal(df: Any, runs_highlight: str) -> np.ndarray:
    """
    Pick the runs-signal array the caller asked to highlight.

    "localized" drops the Anhoej crossings whole-series blanket, leaving only
    the points that form an actual run. Falls back to the plain runs_signal
    column for results built before runs_signal_localized existed.
    """
    if runs_highlight == "none":
        return np.zeros(len(df), dtype=bool)
    if runs_highlight == "localized" and "runs_signal_localized" in df.columns:
        return df["runs_signal_localized"].to_numpy()
    return df["runs_signal"].to_numpy()


def _point_colors(sigma_sig: np.ndarray, runs_sig: np.ndarray) -> list[str]:
    """Per-point colors: brick (sigma) > amber (runs) > data ink (normal)."""
    return [
        SIGMA if s else RUNS if r else NORMAL
        for s, r in zip(sigma_sig, runs_sig)
    ]


def _point_symbols(sigma_sig: np.ndarray, runs_sig: np.ndarray) -> list[str]:
    """Per-point symbols for colorblind accessibility: circle (normal/sigma), diamond (runs)."""
    return [
        "diamond" if (r and not s) else "circle"
        for s, r in zip(sigma_sig, runs_sig)
    ]


def _point_sizes(sigma_sig: np.ndarray, runs_sig: np.ndarray, point_size: float) -> list[float]:
    """Signal points are drawn larger so exceptions carry more ink than routine ones."""
    base = point_size * 6
    return [
        base * 1.3 if (s or r) else base
        for s, r in zip(sigma_sig, runs_sig)
    ]


def _label_decimals(*arrays: np.ndarray) -> int:
    """
    Pick decimal places for the CL/UCL/LCL labels from the spread they span.

    Fixed decimals either round a proportion to nothing ("CL=0.2") or print
    noise on a large count ("CL=1284.0000"). Scaling to the limit spread keeps
    roughly three significant figures of whatever resolution the chart has.
    """
    vals = np.concatenate([np.asarray(a, dtype=float).ravel() for a in arrays if a is not None])
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return 1

    spread = float(np.max(vals) - np.min(vals))
    if spread <= 0:
        # A flat series has no spread to scale by; fall back to magnitude.
        spread = abs(float(vals[0])) or 1.0

    return int(np.clip(2 - math.floor(math.log10(spread)), 0, 4))


def _add_chart_traces(
    fig: go.Figure,
    df: Any,
    show_labels: bool,
    decimals: int | None,
    point_size: float,
    show_95: bool,
    x_pad: float,
    row: int | None = None,
    col: int | None = None,
    part_indices: list[int] | None = None,
    part_labels: list[str] | None = None,
    connect: bool | None = None,
    runs_highlight: str = "all",
    y_percent: bool = False,
    chart_type: str = "",
) -> None:
    """
    Add data/CL/UCL/LCL traces, part boundaries, and notes to fig.
    """
    # An O/E funnel's limits are probability contours, not sigma multiples, so
    # naming them "UCL"/"2σ" would misreport what the reader is looking at.
    if chart_type in ("oe", "oep"):
        outer_names, inner_names = ("99.8%+", "99.8%-"), ("95%+", "95%-")
    else:
        outer_names, inner_names = ("UCL", "LCL"), ("2σ+", "2σ-")
    x = df["x"].tolist()
    y = df["y"].to_numpy(dtype=float)
    cl = df["cl"].to_numpy(dtype=float)
    ucl = df["ucl"].to_numpy(dtype=float)
    lcl = df["lcl"].to_numpy(dtype=float)

    sigma_sig = df["sigma_signal"].to_numpy()
    runs_sig = _resolve_runs_signal(df, runs_highlight)
    colors = _point_colors(sigma_sig, runs_sig)
    symbols = _point_symbols(sigma_sig, runs_sig)
    sizes = _point_sizes(sigma_sig, runs_sig, point_size)

    # Ghost points excluded via exclude=: faded and not counted toward
    # limits or signals (handled upstream in qikit.spc.compute/api).
    excluded = df["excluded"].to_numpy() if "excluded" in df.columns else np.zeros(len(x), dtype=bool)
    opacities = [0.35 if ex else 1.0 for ex in excluded]

    add_kwargs: dict[str, Any] = {}
    if row is not None and col is not None:
        add_kwargs = {"row": row, "col": col}

    # Connectivity: explicit override > auto-detection
    if connect is not None:
        mode = "lines+markers" if connect else "markers"
    else:
        is_categorical = all(isinstance(val, str) for val in x)
        sequential_patterns = ["-", "/", "week", "wk", "case", "obs", "pt"]
        looks_sequential = any(any(pat in str(val).lower() for pat in sequential_patterns) for val in x)
        dots_only = is_categorical and not looks_sequential
        mode = "markers" if dots_only else "lines+markers"

    # Data trace — zorder=2 keeps it above all reference ink
    text = df["notes"].tolist() if "notes" in df.columns else None
    ghost_note = ["excluded" if ex else "" for ex in excluded]
    hovertemplate = "%{x}: %{y}"
    if text:
        hovertemplate += "<br>%{text}"

    if chart_type in ("oe", "oep") and "ci_95_lower" in df.columns:
        # An O/E ratio on its own tells a reader very little: 2.5 could be five deaths
        # against two expected or five hundred against two hundred, and only one of
        # those is worth a conversation. Lead with the counts, then the interval this
        # point's own data supports, then what it would have taken to flag — so a point
        # inside the limits reads as "not enough evidence" rather than "cleared".
        # Pre-formatted strings, because a d3 number format renders NaN literally.
        def _fmt(v: float, places: int) -> str:
            return "n/a" if v is None or np.isnan(v) else f"{v:.{places}f}"

        customdata = [
            [
                f" ({g})" if g else "",
                f"{_fmt(o, 0)} / expected {_fmt(e, 1)}",
                f"{_fmt(lo, 2)}–{_fmt(hi, 2)}",
                _fmt(d, 2),
            ]
            for g, o, e, lo, hi, d in zip(
                ghost_note,
                df["observed"], df["expected"],
                df["ci_95_lower"], df["ci_95_upper"], df["min_detectable_oe"],
            )
        ]
        hovertemplate += (
            "%{customdata[0]}"
            "<br>Observed %{customdata[1]}"
            "<br>95% CI: %{customdata[2]}"
            "<br>Smallest detectable O/E: %{customdata[3]}"
            "<extra></extra>"
        )
    else:
        hovertemplate += "%{customdata}<extra></extra>"
        customdata = [f" ({n})" if n else "" for n in ghost_note]

    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode=mode,
        line=dict(color=NORMAL, width=1),
        marker=dict(color=colors, symbol=symbols, size=sizes, line=dict(width=0), opacity=opacities),
        name="data",
        text=text,
        customdata=customdata,
        hovertemplate=hovertemplate,
        connectgaps=False,
        cliponaxis=False,
        zorder=2,
    ), **add_kwargs)

    # Target line
    if "target" in df:
        target = df["target"].to_numpy(dtype=float)
        has_target = not np.all(np.isnan(target))
        if has_target:
            fig.add_trace(go.Scatter(
                x=x, y=target,
                mode="lines",
                line=dict(color=TARGET, width=1, dash="dot"),
                name="Target",
                hoverinfo="skip",
                zorder=1,
            ), **add_kwargs)

    # Center line
    fig.add_trace(go.Scatter(
        x=x, y=cl,
        mode="lines",
        line=dict(color=CL, width=1),
        name="CL",
        hoverinfo="skip",
        zorder=1,
    ), **add_kwargs)

    # UCL/LCL — light solid hairlines; the direct labels say which is which,
    # so neither a dash pattern nor a fill between them has to carry meaning.
    for arr, name in [(ucl, outer_names[0]), (lcl, outer_names[1])]:
        if not np.all(np.isnan(arr)):
            fig.add_trace(go.Scatter(
                x=x, y=arr,
                mode="lines",
                line=dict(color=LIMIT, width=1),
                name=name,
                hoverinfo="skip",
                zorder=1,
            ), **add_kwargs)

    # 2-sigma warning lines
    if show_95 and not np.all(np.isnan(ucl)):
        if "ucl_95" in df and "lcl_95" in df:
            warn_upper = df["ucl_95"].to_numpy(dtype=float)
            warn_lower = df["lcl_95"].to_numpy(dtype=float)
        else:
            warn_upper = cl + (ucl - cl) * (2.0 / 3.0)
            warn_lower = cl - (ucl - cl) * (2.0 / 3.0)
        for warn_y, name in [(warn_upper, inner_names[0]), (warn_lower, inner_names[1])]:
            fig.add_trace(go.Scatter(
                x=x, y=warn_y,
                mode="lines",
                line=dict(color=WARN, width=1, dash="dot"),
                name=name,
                hoverinfo="skip",
                zorder=1,
            ), **add_kwargs)

    # Direct labels — work in both single and faceted mode
    if show_labels and len(x) > 0:
        # A percent axis displays 100x the stored value, so both the chosen
        # precision and the printed label follow the scale the reader sees.
        scale = 100.0 if y_percent else 1.0
        label_decimals = (
            decimals if decimals is not None
            else _label_decimals(cl * scale, ucl * scale, lcl * scale)
        )
        value_fmt = f"{{:.{label_decimals}{'%' if y_percent else 'f'}}}"
        ann_kwargs: dict[str, Any] = {}
        if row is not None and col is not None:
            ann_kwargs = {"row": row, "col": col}
        for arr, label in [(cl, "CL"), (ucl, outer_names[0]), (lcl, outer_names[1])]:
            valid_idx = np.flatnonzero(~np.isnan(arr))
            if len(valid_idx) == 0:
                continue
            # Anchor at the last point that actually has a value. For a stepped line
            # (variable n, or the S chart's c4(nᵢ)·σ̂ center) the label reads the value
            # at its own x, so a trailing gap must not drag it off the line.
            last = int(valid_idx[-1])
            val = float(arr[last])
            fig.add_annotation(
                x=x[last], y=val,
                text=f"{label}={value_fmt.format(val)}",
                xshift=8 + x_pad * 4,
                showarrow=False, xanchor="left",
                font=dict(size=10, color=TEXT_MUTED),
                **ann_kwargs,
            )

    # Part boundary lines
    if part_indices:
        for boundary_1based in part_indices:
            boundary_0idx = boundary_1based - 1
            if 0 <= boundary_0idx < len(x):
                x_val = x[boundary_0idx]
                label_text = None
                if part_labels:
                    try:
                        idx = part_indices.index(boundary_1based)
                        label_text = part_labels[idx]
                    except (ValueError, IndexError):
                        pass

                fig.add_vline(
                    x=x_val,
                    line=dict(color=LIMIT, width=1),
                    annotation_text=label_text or "",
                    annotation_position="top",
                    annotation_font=dict(size=9, color=TEXT_FAINT),
                    **add_kwargs
                )

    # Note annotations
    if "notes" in df.columns:
        for _, row_data in df.iterrows():
            note = str(row_data.get("notes", ""))
            if note.strip():
                fig.add_annotation(
                    x=row_data["x"], y=row_data["y"],
                    text=note,
                    showarrow=True, arrowhead=1,
                    arrowcolor=AXIS, arrowwidth=1,
                    font=dict(size=9, color=TEXT_MUTED),
                    ax=0, ay=-25,
                    **add_kwargs
                )


# Shown under an underpowered O/E funnel when the caller supplied no caption of their
# own. summary["underpowered"] is enough for code, but these charts get screenshotted
# into credentialing packets, and no summary key travels with the image — the caveat
# has to be part of the picture.
_UNDERPOWERED_CAPTION = (
    "Most points lack the volume to detect a doubling of risk; absence of a signal "
    "is not evidence of acceptable performance."
)


def _effective_caption(result: Any) -> str | None:
    """The caller's caption, or the underpowered warning when they gave none."""
    caption = getattr(result, "caption", None)
    if caption:
        return caption
    summary = getattr(result, "summary", None) or {}
    return _UNDERPOWERED_CAPTION if summary.get("underpowered") else None


def _configure_layout(
    fig: go.Figure,
    result: Any,
    show_grid: bool,
    y_neg: bool,
    y_expand: float | None,
    y_percent: bool,
    x_angle: int | None,
    x_format: str | None,
    flip: bool,
    x_order: list | str | None = None,
    height: int | None = None,
    width: int | None = None,
    x_nticks_all: bool = False,
    show_x_labels: bool = True,
) -> None:
    """Shared layout and axis styling for single and faceted plots."""
    apply_tufte_theme(fig)

    # Categorical x-axis: explicit type + optional ordering
    x_vals = result.data["x"].tolist()
    is_categorical = all(isinstance(v, str) for v in x_vals)
    if is_categorical:
        fig.update_xaxes(type="category")
        if x_order is not None:
            if isinstance(x_order, list):
                fig.update_xaxes(categoryorder="array", categoryarray=x_order)
            else:
                fig.update_xaxes(categoryorder=x_order)

    # nticks: restrict x ticks only for numeric/time axes; for categorical, show all or limit
    if x_nticks_all or is_categorical:
        fig.update_xaxes(nticks=0)  # 0 = Plotly auto, shows all category labels
    else:
        fig.update_xaxes(nticks=5)

    if not show_x_labels:
        # The category axis and %{x} in the hovertemplate keep the full label
        # available on hover, so this is purely a subtraction of axis ink.
        fig.update_xaxes(showticklabels=False, ticks="")

    title_text = result.title
    if hasattr(result, "signals") and result.signals and title_text:
        title_text += " ⚠"

    full_title = title_text
    if hasattr(result, "subtitle") and result.subtitle:
        full_title += f"<br><sup>{result.subtitle}</sup>"

    top_margin = 30 if not result.title else 60
    size_kwargs: dict[str, Any] = {}
    if height is not None:
        size_kwargs["height"] = height
    if width is not None:
        size_kwargs["width"] = width

    fig.update_layout(
        title=dict(text=full_title, font=dict(size=15, color=TEXT), x=0, xanchor="left"),
        xaxis_title=result.xlab,
        yaxis_title=result.ylab,
        margin=dict(l=50, r=100, t=top_margin, b=80),
        **size_kwargs,
    )

    caption = _effective_caption(result)
    if caption:
        fig.add_annotation(
            text=caption, xref="paper", yref="paper",
            x=0, y=-0.2, showarrow=False,
            font=dict(size=10, color=TEXT_FAINT), xanchor="left",
        )

    grid_color = GRID if show_grid else "rgba(0,0,0,0)"
    fig.update_xaxes(showgrid=show_grid, gridcolor=grid_color)
    fig.update_yaxes(showgrid=show_grid, gridcolor=grid_color)

    if not y_neg:
        fig.update_yaxes(rangemode="nonnegative")
    
    if y_expand is not None:
        y_vals = result.data["y"].to_numpy(dtype=float)
        y_valid = y_vals[~np.isnan(y_vals)]
        curr_min = np.nanmin(y_valid) if len(y_valid) > 0 else 0
        curr_max = np.nanmax(y_valid) if len(y_valid) > 0 else 0
        new_min = min(curr_min, y_expand) if y_neg else max(0, min(curr_min, y_expand))
        new_max = max(curr_max, y_expand)
        fig.update_yaxes(range=[new_min, new_max * 1.05])

    if y_percent:
        fig.update_yaxes(tickformat=".0%")
    if x_angle is not None:
        fig.update_xaxes(tickangle=x_angle)
    if x_format is not None:
        fig.update_xaxes(tickformat=x_format)
    if flip:
        fig.update_layout(xaxis=dict(autorange="reversed"))


def _plot_faceted(
    result: Any,
    nrow: int | None,
    ncol: int | None,
    scales: str,
    show_labels: bool,
    show_95: bool,
    decimals: int | None,
    point_size: float,
    x_angle: int | None,
    x_pad: float,
    x_format: str | None,
    y_expand: float | None,
    y_neg: bool,
    y_percent: bool,
    flip: bool,
    show_grid: bool,
    x_order: list | str | None = None,
    height: int | None = None,
    width: int | None = None,
    connect: bool | None = None,
    x_nticks_all: bool = False,
    runs_highlight: str = "all",
    show_x_labels: bool = True,
) -> go.Figure:
    """Render a faceted SPCResult as a multi-panel Plotly Figure."""
    facet_vals = list(result.data["facet"].unique())
    n_facets = len(facet_vals)

    if ncol is None and nrow is None:
        ncol = min(3, n_facets)
        nrow = math.ceil(n_facets / ncol)
    elif ncol is None:
        ncol = math.ceil(n_facets / nrow)
    elif nrow is None:
        nrow = math.ceil(n_facets / ncol)

    shared_y = (scales == "fixed")
    fig = make_subplots(
        rows=nrow, cols=ncol,
        shared_xaxes=True,
        shared_yaxes=shared_y,
        horizontal_spacing=0.06,
        vertical_spacing=0.10,
        subplot_titles=[str(v) for v in facet_vals],
    )

    # make_subplots writes the panel titles as annotations; restyle them before
    # traces append their own (direct labels, notes) to this same list.
    for ann in fig.layout.annotations:
        ann.font = dict(size=11, color=TEXT_MUTED)

    for idx, fv in enumerate(facet_vals):
        r_row = idx // ncol + 1
        r_col = idx % ncol + 1
        df_sub = result.data[result.data["facet"] == fv]
        
        _add_chart_traces(
            fig, df_sub,
            show_labels=show_labels,
            decimals=decimals,
            point_size=point_size,
            show_95=show_95,
            x_pad=x_pad,
            row=r_row, col=r_col,
            connect=connect,
            runs_highlight=runs_highlight,
            y_percent=y_percent,
            chart_type=result.chart_type,
        )

    _configure_layout(
        fig, result, show_grid, y_neg, y_expand,
        y_percent, x_angle, x_format, flip, x_order=x_order,
        height=height, width=width, x_nticks_all=x_nticks_all,
        show_x_labels=show_x_labels,
    )

    # Shared axes hide the tick labels on inner panels; the tick marks left
    # behind carry no information, so drop them. Runs after _configure_layout,
    # which re-applies ticks="outside" to every axis.
    for axis_name in fig.layout:
        if axis_name.startswith(("xaxis", "yaxis")) and fig.layout[axis_name].showticklabels is False:
            fig.layout[axis_name].ticks = ""

    return fig


def plot_pareto(result: Any, x_angle: int | None = None, **_kwargs: Any) -> go.Figure:
    """Render a ParetoResult as a Plotly Figure."""
    df = result.data
    
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Bars
    fig.add_trace(
        go.Bar(
            x=df["category"], 
            y=df["count"], 
            name=result.ylab,
            marker_color=NORMAL,
            hovertemplate="%{x}: %{y}<extra></extra>"
        ),
        secondary_y=False,
    )
    
    # Cumulative line
    fig.add_trace(
        go.Scatter(
            x=df["category"], 
            y=df["cum_percent"], 
            name="Cumulative %",
            mode="lines+markers",
            line=dict(color=SIGMA, width=2),
            marker=dict(size=6),
            hovertemplate="%{x}: %{y:.1f}%<extra></extra>"
        ),
        secondary_y=True,
    )
    
    # Build title with subtitle if present
    full_title = result.title
    if hasattr(result, "subtitle") and result.subtitle:
        full_title += f"<br><sup>{result.subtitle}</sup>"

    fig.update_layout(
        title=dict(text=full_title, font=dict(size=14)),
        xaxis_title=result.xlab,
        yaxis_title=result.ylab,
        yaxis2_title="Cumulative %",
        margin=dict(l=50, r=50, t=60, b=80),
    )
    apply_tufte_theme(fig)
    
    if hasattr(result, "caption") and result.caption:
        fig.add_annotation(
            text=result.caption,
            xref="paper", yref="paper",
            x=0, y=-0.2,
            showarrow=False,
            font=dict(size=10, color="#777"),
            xanchor="left",
        )
    
    fig.update_yaxes(range=[0, df["count"].sum() * 1.05], secondary_y=False)
    fig.update_yaxes(range=[0, 105], ticksuffix="%", secondary_y=True)
    
    if x_angle is not None:
        fig.update_xaxes(tickangle=x_angle)
        
    fig.update_xaxes(showline=True, linecolor=AXIS)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, secondary_y=False)

    return fig


def plot_bchart(result: Any, **_kwargs: Any) -> go.Figure:
    """Render a BChartResult as a Plotly Figure."""
    df = result.data
    limit = result.limit
    limit2 = -limit
    
    fig = go.Figure()
    
    # Upward CUSUM
    fig.add_trace(go.Scatter(
        x=df["x"], y=df["cusum_up"],
        mode="lines",
        line=dict(color=NORMAL, width=1.5),
        name="CUSUM Up",
        hovertemplate="Case %{x}<br>CUSUM Up: %{y:.2f}<extra></extra>"
    ))
    
    # Downward CUSUM
    fig.add_trace(go.Scatter(
        x=df["x"], y=df["cusum_down"],
        mode="lines",
        line=dict(color=NORMAL, width=1.5, dash="dot"),
        name="CUSUM Down",
        hovertemplate="Case %{x}<br>CUSUM Down: %{y:.2f}<extra></extra>"
    ))
    
    # Signals
    sig_up = df[df["signal_up"]]
    if not sig_up.empty:
        fig.add_trace(go.Scatter(
            x=sig_up["x"], y=[limit] * len(sig_up),
            mode="markers",
            marker=dict(color=SIGMA, size=10, symbol="triangle-up"),
            name="Signal Up",
            hoverinfo="skip"
        ))
        
    sig_down = df[df["signal_down"]]
    if not sig_down.empty:
        fig.add_trace(go.Scatter(
            x=sig_down["x"], y=[limit2] * len(sig_down),
            mode="markers",
            marker=dict(color=SIGMA, size=10, symbol="triangle-down"),
            name="Signal Down",
            hoverinfo="skip"
        ))

    # Threshold lines
    fig.add_hline(y=limit, line=dict(color=CL, width=1, dash="dash"))
    fig.add_hline(y=limit2, line=dict(color=CL, width=1, dash="dash"))
    fig.add_hline(y=0, line=dict(color=CL, width=1))
    
    # Build title with subtitle if present
    full_title = result.title
    if hasattr(result, "subtitle") and result.subtitle:
        full_title += f"<br><sup>{result.subtitle}</sup>"

    fig.update_layout(
        title=dict(text=full_title, font=dict(size=14)),
        xaxis_title=result.xlab,
        yaxis_title=result.ylab,
        margin=dict(l=50, r=50, t=60, b=80),
    )
    apply_tufte_theme(fig)
    
    if hasattr(result, "caption") and result.caption:
        fig.add_annotation(
            text=result.caption,
            xref="paper", yref="paper",
            x=0, y=-0.2,
            showarrow=False,
            font=dict(size=10, color="#777"),
            xanchor="left",
        )
    
    fig.update_xaxes(showline=True, linecolor=AXIS)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False)

    return fig


def plot_result(
    result: Any,
    show_grid: bool = False,
    show_labels: bool = True,
    show_95: bool = False,
    decimals: int | None = None,
    point_size: float = 1.5,
    x_angle: int | None = None,
    x_pad: float = 1.0,
    x_format: str | None = None,
    y_expand: float | None = None,
    y_neg: bool = True,
    y_percent: bool = False,
    flip: bool = False,
    nrow: int | None = None,
    ncol: int | None = None,
    scales: str = "fixed",
    part_labels: list[str] | None = None,
    part_indices: list[int] | None = None,
    x_order: list | str | None = None,
    height: int | None = None,
    width: int | None = None,
    connect: bool | None = None,
    x_nticks_all: bool = False,
    runs_highlight: str = "all",
    show_x_labels: bool = True,
    **_kwargs: Any,
) -> go.Figure:
    """
    Render an SPCResult as a Plotly Figure.
    """
    # plot(**overrides) bypasses qic(), so this is the only guard on that path.
    if runs_highlight not in VALID_RUNS_HIGHLIGHT:
        raise ValueError(
            f"runs_highlight must be one of {VALID_RUNS_HIGHLIGHT}, got {runs_highlight!r}."
        )

    if "facet" in result.data.columns:
        return _plot_faceted(
            result, nrow=nrow, ncol=ncol, scales=scales,
            show_labels=show_labels, show_95=show_95,
            decimals=decimals, point_size=point_size,
            x_angle=x_angle, x_pad=x_pad, x_format=x_format,
            y_expand=y_expand, y_neg=y_neg, y_percent=y_percent,
            flip=flip, show_grid=show_grid, x_order=x_order,
            height=height, width=width,
            connect=connect, x_nticks_all=x_nticks_all,
            runs_highlight=runs_highlight,
            show_x_labels=show_x_labels,
        )

    df = result.data
    fig = go.Figure()

    _add_chart_traces(
        fig, df,
        show_labels=show_labels,
        decimals=decimals,
        point_size=point_size,
        show_95=show_95,
        x_pad=x_pad,
        part_indices=part_indices,
        part_labels=part_labels,
        connect=connect,
        runs_highlight=runs_highlight,
        y_percent=y_percent,
        chart_type=result.chart_type,
    )

    _configure_layout(
        fig, result, show_grid, y_neg, y_expand,
        y_percent, x_angle, x_format, flip, x_order=x_order,
        height=height, width=width, x_nticks_all=x_nticks_all,
        show_x_labels=show_x_labels,
    )

    return fig
