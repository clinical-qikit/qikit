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

if TYPE_CHECKING:
    from qikit import SPCResult

# Colors
_NORMAL = "#888888"
_CL = "#333333"
_SIGMA = "#d62728"    # red
_RUNS = "#ff7f0e"     # orange
_GRID = "#eeeeee"
_WARN = "#cccccc"


def _point_colors(sigma_sig: np.ndarray, runs_sig: np.ndarray) -> list[str]:
    """Per-point colors: red (sigma) > orange (runs) > gray (normal)."""
    return [
        _SIGMA if s else _RUNS if r else _NORMAL
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
) -> None:
    """
    Add data/CL/UCL/LCL traces to fig.

    If row/col are None, traces are added to a plain Figure (no row/col args).
    If row/col are integers, traces are added to a subplot at that position.
    """
    x = df["x"].tolist()
    y = df["y"].to_numpy(dtype=float)
    cl = df["cl"].to_numpy(dtype=float)
    ucl = df["ucl"].to_numpy(dtype=float)
    lcl = df["lcl"].to_numpy(dtype=float)

    colors = _point_colors(
        df["sigma_signal"].to_numpy(),
        df["runs_signal"].to_numpy(),
    )

    add_kwargs: dict[str, Any] = {}
    if row is not None and col is not None:
        add_kwargs = {"row": row, "col": col}

    # Data line + markers
    has_notes = "notes" in df
    hovertemplate = "%{x}: %{y}<br>%{text}<extra></extra>" if has_notes else "%{x}: %{y}<extra></extra>"
    text = df["notes"].tolist() if has_notes else None

    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines+markers",
        line=dict(color=_NORMAL, width=1),
        marker=dict(color=colors, size=point_size * 4, line=dict(width=0)),
        name="data",
        text=text,
        hovertemplate=hovertemplate,
    ), **add_kwargs)

    # Target line
    if "target" in df:
        target = df["target"].to_numpy(dtype=float)
        has_target = not np.all(np.isnan(target))
        if has_target:
            fig.add_trace(go.Scatter(
                x=x, y=target,
                mode="lines",
                line=dict(color="#2ca02c", width=1, dash="dashdot"),  # Green dashed line
                name="Target",
                hoverinfo="skip",
            ), **add_kwargs)

    # Center line
    fig.add_trace(go.Scatter(
        x=x, y=cl,
        mode="lines",
        line=dict(color=_CL, width=1),
        name="CL",
        hoverinfo="skip",
    ), **add_kwargs)

    # UCL (skip if all NaN — e.g. run chart)
    has_ucl = not np.all(np.isnan(ucl))
    if has_ucl:
        fig.add_trace(go.Scatter(
            x=x, y=ucl,
            mode="lines",
            line=dict(color=_CL, width=1, dash="dash"),
            name="UCL",
            hoverinfo="skip",
        ), **add_kwargs)

    # LCL (skip if all NaN)
    has_lcl = not np.all(np.isnan(lcl))
    if has_lcl:
        fig.add_trace(go.Scatter(
            x=x, y=lcl,
            mode="lines",
            line=dict(color=_CL, width=1, dash="dash"),
            name="LCL",
            hoverinfo="skip",
        ), **add_kwargs)

    # 2-sigma warning lines
    if show_95 and has_ucl:
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
            ), **add_kwargs)

    # Direct labels at right edge (only for non-subplot case)
    if show_labels and len(x) > 0 and row is None:
        x_last = x[-1]
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
            )


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
    y_neg: bool,
    y_percent: bool,
    flip: bool,
    show_grid: bool,
) -> go.Figure:
    """Render a faceted SPCResult as a multi-panel Plotly Figure."""
    facet_vals = list(result.data["facet"].unique())
    n_facets = len(facet_vals)

    if ncol is None and nrow is None:
        ncol = min(3, n_facets)
        nrow = math.ceil(n_facets / ncol)
    elif ncol is None:
        ncol = math.ceil(n_facets / nrow)  # type: ignore[arg-type]
    elif nrow is None:
        nrow = math.ceil(n_facets / ncol)

    shared_y = (scales == "fixed")
    fig = make_subplots(
        rows=nrow, cols=ncol,
        shared_yaxes=shared_y,
        subplot_titles=[str(v) for v in facet_vals],
    )

    for idx, fv in enumerate(facet_vals):
        row = idx // ncol + 1
        col = idx % ncol + 1
        df_sub = result.data[result.data["facet"] == fv]
        _add_chart_traces(
            fig, df_sub,
            show_labels=show_labels,
            decimals=decimals,
            point_size=point_size,
            show_95=show_95,
            x_pad=x_pad,
            row=row, col=col,
        )

    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        title=dict(text=result.title, font=dict(size=14)),
        margin=dict(l=50, r=80, t=60, b=50),
    )

    grid_color = _GRID if show_grid else "white"
    fig.update_xaxes(
        showgrid=show_grid, gridcolor=grid_color,
        zeroline=False, showline=True, linecolor="#cccccc",
    )
    fig.update_yaxes(
        showgrid=show_grid, gridcolor=grid_color,
        zeroline=False, showline=True, linecolor="#cccccc",
    )

    if not y_neg:
        fig.update_yaxes(rangemode="nonnegative")
    if y_percent:
        fig.update_yaxes(tickformat=".0%")
    if x_angle is not None:
        fig.update_xaxes(tickangle=x_angle)
    if flip:
        fig.update_layout(xaxis=dict(autorange="reversed"))

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
    y_neg: bool = True,
    y_percent: bool = False,
    flip: bool = False,
    nrow: int | None = None,
    ncol: int | None = None,
    scales: str = "fixed",
    part_labels: list[str] | None = None,
    part_indices: list[int] | None = None,
    **_kwargs: Any,
) -> go.Figure:
    """
    Render an SPCResult as a Plotly Figure.

    Called by SPCResult.plot(). Display options come from _plot_opts
    (set at qic() time) merged with any overrides passed here.
    """
    # Route to faceted plot if 'facet' column present
    if "facet" in result.data.columns:
        return _plot_faceted(
            result,
            show_grid=show_grid,
            show_labels=show_labels,
            show_95=show_95,
            decimals=decimals,
            point_size=point_size,
            x_angle=x_angle,
            x_pad=x_pad,
            y_neg=y_neg,
            y_percent=y_percent,
            flip=flip,
            nrow=nrow,
            ncol=ncol,
            scales=scales,
        )

    df = result.data
    x = df["x"].tolist()
    y = df["y"].to_numpy(dtype=float)
    cl = df["cl"].to_numpy(dtype=float)
    ucl = df["ucl"].to_numpy(dtype=float)
    lcl = df["lcl"].to_numpy(dtype=float)

    colors = _point_colors(
        df["sigma_signal"].to_numpy(),
        df["runs_signal"].to_numpy(),
    )

    fig = go.Figure()

    # Data line + markers
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines+markers",
        line=dict(color=_NORMAL, width=1),
        marker=dict(color=colors, size=point_size * 4, line=dict(width=0)),
        name="data",
        hovertemplate="%{x}: %{y}<extra></extra>",
    ))

    # Center line
    fig.add_trace(go.Scatter(
        x=x, y=cl,
        mode="lines",
        line=dict(color=_CL, width=1),
        name="CL",
        hoverinfo="skip",
    ))

    # UCL (skip if all NaN — e.g. run chart)
    has_ucl = not np.all(np.isnan(ucl))
    if has_ucl:
        fig.add_trace(go.Scatter(
            x=x, y=ucl,
            mode="lines",
            line=dict(color=_CL, width=1, dash="dash"),
            name="UCL",
            hoverinfo="skip",
        ))

    # LCL (skip if all NaN)
    has_lcl = not np.all(np.isnan(lcl))
    if has_lcl:
        fig.add_trace(go.Scatter(
            x=x, y=lcl,
            mode="lines",
            line=dict(color=_CL, width=1, dash="dash"),
            name="LCL",
            hoverinfo="skip",
        ))

    # 2-sigma warning lines
    if show_95 and has_ucl:
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
            ))

    # Direct labels at right edge
    if show_labels and len(x) > 0:
        x_last = x[-1]
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
            )

    # Part boundary vertical lines
    if part_indices:
        for boundary_1based in part_indices:
            boundary_0idx = boundary_1based - 1
            if 0 <= boundary_0idx < len(x):
                x_boundary = x[boundary_0idx]
                label_text = None
                if part_labels:
                    label_idx = part_indices.index(boundary_1based)
                    if label_idx < len(part_labels):
                        label_text = part_labels[label_idx]
                fig.add_vline(
                    x=x_boundary,
                    line=dict(color="#999999", width=1, dash="dash"),
                    annotation_text=label_text or "",
                    annotation_position="top",
                )

    # Notes annotations
    if "note" in df.columns:
        for _, row_data in df.iterrows():
            note = str(row_data.get("note", ""))
            if note.strip():
                fig.add_annotation(
                    x=row_data["x"], y=row_data["y"],
                    text=note,
                    showarrow=True, arrowhead=2,
                    font=dict(size=9, color="#555"),
                    ax=0, ay=-25,
                )

    # Layout
    title_text = result.title
    if result.signals and title_text:
        title_text += " ⚠"

    fig.update_layout(
        title=dict(text=title_text, font=dict(size=14)),
        xaxis_title=result.xlab,
        yaxis_title=result.ylab,
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        margin=dict(l=50, r=100, t=50, b=50),
    )

    grid_color = _GRID if show_grid else "white"
    fig.update_xaxes(
        showgrid=show_grid, gridcolor=grid_color,
        zeroline=False, showline=True, linecolor="#cccccc",
    )
    fig.update_yaxes(
        showgrid=show_grid, gridcolor=grid_color,
        zeroline=False, showline=True, linecolor="#cccccc",
    )

    if not y_neg:
        fig.update_yaxes(rangemode="nonnegative")
    if y_percent:
        fig.update_yaxes(tickformat=".0%")
    if x_angle is not None:
        fig.update_xaxes(tickangle=x_angle)
    if flip:
        fig.update_layout(xaxis=dict(autorange="reversed"))

    return fig
