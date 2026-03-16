"""
render_shared.py — Shared Plotly utilities and Tufte theme for qikit.
"""

from __future__ import annotations

from typing import Any
import plotly.graph_objects as go

# Colors
NORMAL = "#888888"
CL = "#333333"
SIGMA = "#d62728"    # red
RUNS = "#ff7f0e"     # orange
GRID = "#eeeeee"
WARN = "#999999"

def apply_tufte_theme(fig: go.Figure) -> go.Figure:
    """Apply qikit Tufte theme: white bg, no borders, minimal grid."""
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Arial, sans-serif", size=12, color=CL),
        margin=dict(l=50, r=80, t=60, b=50),
        showlegend=False,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#cccccc",
            font=dict(size=11, color=CL),
        ),
    )

    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor="#cccccc",
        ticks="outside",
        tickcolor="#cccccc",
        nticks=5,
    )

    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor="#cccccc",
        ticks="outside",
        tickcolor="#cccccc",
        nticks=5,
    )

    return fig
