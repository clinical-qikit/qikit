"""
render.py — Plotly rendering for SPCResult.

Design principles (Tufte, Visual Display of Quantitative Information):
- Maximize data-ink ratio; every pixel earns its place
- No plot border, no background fill, minimal grid
- Normal points: small, muted (#888)
- Signal points: the ONLY color — red (sigma), orange (runs)
- CL/UCL/LCL labeled directly at right edge; no legend
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .utils import apply_tufte_theme, NORMAL, CL, SIGMA, RUNS, GRID, WARN

if TYPE_CHECKING:
    pass

# Colors used locally (aliases for shared)
_NORMAL = NORMAL
_CL = CL
_SIGMA = SIGMA
_RUNS = RUNS
_GRID = GRID
_WARN = WARN


def _point_colors(sigma_sig: np.ndarray, runs_sig: np.ndarray) -> list[str]:
    """Per-point colors: red (sigma) > orange (runs) > gray (normal)."""
    return [
        _SIGMA if s else _RUNS if r else _NORMAL
        for s, r in zip(sigma_sig, runs_sig)
    ]


def _point_symbols(sigma_sig: np.ndarray, runs_sig: np.ndarray) -> list[str]:
    """Per-point symbols for colorblind accessibility: circle (normal/sigma), diamond (runs)."""
    return [
        "diamond" if (r and not s) else "circle"
        for s, r in zip(sigma_sig, runs_sig)
    ]


def _add_chart_traces(
    fig: go.Figure,
    df: Any,
    show_labels: bool,
    decimals: int,
    point_size: float,
    show_95: bool,
    x_pad: float,
    row: int | None = None,
    col: int | None = None,
    part_indices: list[int] | None = None,
    part_labels: list[str] | None = None,
) -> None:
    """
    Add data/CL/UCL/LCL traces, part boundaries, and notes to fig.
    """
    x = df["x"].tolist()
    y = df["y"].to_numpy(dtype=float)
    cl = df["cl"].to_numpy(dtype=float)
    ucl = df["ucl"].to_numpy(dtype=float)
    lcl = df["lcl"].to_numpy(dtype=float)

    sigma_sig = df["sigma_signal"].to_numpy()
    runs_sig = df["runs_signal"].to_numpy()
    colors = _point_colors(sigma_sig, runs_sig)
    symbols = _point_symbols(sigma_sig, runs_sig)

    add_kwargs: dict[str, Any] = {}
    if row is not None and col is not None:
        add_kwargs = {"row": row, "col": col}

    # Smart connectivity: markers only if categorical and not time-series
    is_categorical = all(isinstance(val, str) for val in x)
    sequential_patterns = ["-", "/", "w", "case", "obs", "pt"]
    looks_sequential = any(any(pat in str(val).lower() for pat in sequential_patterns) for val in x)
    dots_only = is_categorical and (not looks_sequential)
    mode = "markers" if dots_only else "lines+markers"

    # Data trace — zorder=2 keeps it above all reference ink
    text = df["notes"].tolist() if "notes" in df.columns else None
    hovertemplate = "%{x}: %{y}"
    if text:
        hovertemplate += "<br>%{text}"
    hovertemplate += "<extra></extra>"

    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode=mode,
        line=dict(color=_NORMAL, width=1),
        marker=dict(color=colors, symbol=symbols, size=point_size * 4, line=dict(width=0)),
        name="data",
        text=text,
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
                line=dict(color="#2ca02c", width=1, dash="dashdot"),
                name="Target",
                hoverinfo="skip",
                zorder=1,
            ), **add_kwargs)

    # Center line
    fig.add_trace(go.Scatter(
        x=x, y=cl,
        mode="lines",
        line=dict(color=_CL, width=1),
        name="CL",
        hoverinfo="skip",
        zorder=1,
    ), **add_kwargs)

    # UCL/LCL — fill band when both limits exist (one shape replaces two lines)
    has_ucl = not np.all(np.isnan(ucl))
    has_lcl = not np.all(np.isnan(lcl))
    if has_ucl and has_lcl:
        fig.add_trace(go.Scatter(
            x=x, y=lcl,
            mode="lines",
            line=dict(color=_CL, width=1, dash="dash"),
            name="LCL",
            hoverinfo="skip",
            zorder=1,
        ), **add_kwargs)
        fig.add_trace(go.Scatter(
            x=x, y=ucl,
            mode="lines",
            line=dict(color=_CL, width=1, dash="dash"),
            fill="tonexty",
            fillcolor="rgba(51,51,51,0.04)",
            name="UCL",
            hoverinfo="skip",
            zorder=1,
        ), **add_kwargs)
    else:
        for arr, name in [(ucl, "UCL"), (lcl, "LCL")]:
            if not np.all(np.isnan(arr)):
                fig.add_trace(go.Scatter(
                    x=x, y=arr,
                    mode="lines",
                    line=dict(color=_CL, width=1, dash="dash"),
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
        for warn_y, name in [(warn_upper, "2σ+"), (warn_lower, "2σ-")]:
            fig.add_trace(go.Scatter(
                x=x, y=warn_y,
                mode="lines",
                line=dict(color=_WARN, width=1, dash="dot"),
                name=name,
                hoverinfo="skip",
                zorder=1,
            ), **add_kwargs)

    # Direct labels — work in both single and faceted mode
    if show_labels and len(x) > 0:
        x_last = x[-1]
        ann_kwargs: dict[str, Any] = {}
        if row is not None and col is not None:
            ann_kwargs = {"row": row, "col": col}
        for arr, label in [(cl, "CL"), (ucl, "UCL"), (lcl, "LCL")]:
            valid = arr[~np.isnan(arr)]
            if len(valid) == 0:
                continue
            val = float(valid[-1])
            fig.add_annotation(
                x=x_last, y=val,
                text=f"{label}={val:.{decimals}f}",
                xshift=8 + x_pad * 4,
                showarrow=False, xanchor="left",
                font=dict(size=10, color=_CL),
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
                    line=dict(color="#999999", width=1, dash="dash"),
                    annotation_text=label_text or "",
                    annotation_position="top",
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
                    font=dict(size=9, color="#555"),
                    ax=0, ay=-25,
                    **add_kwargs
                )


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
) -> None:
    """Shared layout and axis styling for single and faceted plots."""
    apply_tufte_theme(fig)

    # Categorical x-axis: explicit type + optional ordering
    x_vals = result.data["x"].tolist()
    if all(isinstance(v, str) for v in x_vals):
        fig.update_xaxes(type="category")
        if x_order is not None:
            if isinstance(x_order, list):
                fig.update_xaxes(categoryorder="array", categoryarray=x_order)
            else:
                fig.update_xaxes(categoryorder=x_order)

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
        title=dict(text=full_title, font=dict(size=14)),
        xaxis_title=result.xlab,
        yaxis_title=result.ylab,
        margin=dict(l=50, r=100, t=top_margin, b=80),
        **size_kwargs,
    )

    if hasattr(result, "caption") and result.caption:
        fig.add_annotation(
            text=result.caption, xref="paper", yref="paper",
            x=0, y=-0.2, showarrow=False,
            font=dict(size=10, color="#777"), xanchor="left",
        )

    grid_color = _GRID if show_grid else "rgba(0,0,0,0)"
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
    decimals: int,
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
        )

    _configure_layout(
        fig, result, show_grid, y_neg, y_expand,
        y_percent, x_angle, x_format, flip, x_order=x_order,
        height=height, width=width,
    )

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
            marker_color=_NORMAL,
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
            line=dict(color=_SIGMA, width=2),
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
        
    fig.update_xaxes(showline=True, linecolor="#cccccc")
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, secondary_y=False)
    
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
        line=dict(color=_NORMAL, width=1.5),
        name="CUSUM Up",
        hovertemplate="Case %{x}<br>CUSUM Up: %{y:.2f}<extra></extra>"
    ))
    
    # Downward CUSUM
    fig.add_trace(go.Scatter(
        x=df["x"], y=df["cusum_down"],
        mode="lines",
        line=dict(color=_NORMAL, width=1.5, dash="dot"),
        name="CUSUM Down",
        hovertemplate="Case %{x}<br>CUSUM Down: %{y:.2f}<extra></extra>"
    ))
    
    # Signals
    sig_up = df[df["signal_up"]]
    if not sig_up.empty:
        fig.add_trace(go.Scatter(
            x=sig_up["x"], y=[limit] * len(sig_up),
            mode="markers",
            marker=dict(color=_SIGMA, size=10, symbol="triangle-up"),
            name="Signal Up",
            hoverinfo="skip"
        ))
        
    sig_down = df[df["signal_down"]]
    if not sig_down.empty:
        fig.add_trace(go.Scatter(
            x=sig_down["x"], y=[limit2] * len(sig_down),
            mode="markers",
            marker=dict(color=_SIGMA, size=10, symbol="triangle-down"),
            name="Signal Down",
            hoverinfo="skip"
        ))

    # Threshold lines
    fig.add_hline(y=limit, line=dict(color=_CL, width=1, dash="dash"))
    fig.add_hline(y=limit2, line=dict(color=_CL, width=1, dash="dash"))
    fig.add_hline(y=0, line=dict(color=_CL, width=1))
    
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
    
    fig.update_xaxes(showline=True, linecolor="#cccccc")
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, zeroline=False)
    
    return fig


def plot_result(
    result: Any,
    show_grid: bool = False,
    show_labels: bool = True,
    show_95: bool = False,
    decimals: int = 1,
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
    **_kwargs: Any,
) -> go.Figure:
    """
    Render an SPCResult as a Plotly Figure.
    """
    if "facet" in result.data.columns:
        return _plot_faceted(
            result, nrow=nrow, ncol=ncol, scales=scales,
            show_labels=show_labels, show_95=show_95,
            decimals=decimals, point_size=point_size,
            x_angle=x_angle, x_pad=x_pad, x_format=x_format,
            y_expand=y_expand, y_neg=y_neg, y_percent=y_percent,
            flip=flip, show_grid=show_grid, x_order=x_order,
            height=height, width=width,
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
    )

    _configure_layout(
        fig, result, show_grid, y_neg, y_expand,
        y_percent, x_angle, x_format, flip, x_order=x_order,
        height=height, width=width,
    )

    return fig
