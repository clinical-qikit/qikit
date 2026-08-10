"""
utils.py — Shared Plotly utilities and Tufte theme for qikit.

Ink hierarchy: the data carries the darkest routine ink; every reference
element (center line, control limits, axes, grid) recedes to a lighter gray,
so the eye lands on the series first. Color is reserved for meaning —
signals and the target — and is desaturated so it reads as emphasis rather
than decoration.
"""

from __future__ import annotations

import plotly.graph_objects as go

# Data ink
NORMAL = "#3a3a3a"   # series line and routine points

# Reference ink, in descending salience
CL = "#9a9a9a"       # center line
LIMIT = "#c4c4c4"    # control limits, part boundaries
WARN = "#d6d6d6"     # 2-sigma lines
AXIS = "#d9d9d9"     # axis lines, ticks, hover border, note arrows
GRID = "#f2f2f2"     # optional grid

# Meaning
SIGMA = "#b13b31"    # sigma signal — muted brick
RUNS = "#d99a2b"     # runs signal — muted amber
TARGET = "#4a7a5c"   # target — desaturated sage, kept darker than the
                     # limits so the goal line stays legible as meaning

# Type
TEXT = "#262626"        # title
TEXT_MUTED = "#6e6e6e"  # tick labels, direct labels, notes
TEXT_FAINT = "#9a9a9a"  # caption, part labels

FONT_FAMILY = '-apple-system, "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif'


def apply_tufte_theme(fig: go.Figure) -> go.Figure:
    """Apply qikit Tufte theme: white bg, no legend, minimal frame and grid."""
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family=FONT_FAMILY, size=12, color="#4a4a4a"),
        margin=dict(l=50, r=80, t=60, b=50),
        showlegend=False,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="white",
            bordercolor=AXIS,
            font=dict(size=11, color=TEXT_MUTED),
        ),
    )

    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor=AXIS,
        ticks="outside",
        ticklen=4,
        tickcolor=AXIS,
        tickfont=dict(size=11, color=TEXT_MUTED),
    )

    # No y spine — the tick labels alone carry the scale.
    fig.update_yaxes(
        showgrid=False,
        zeroline=False,
        showline=False,
        ticks="outside",
        ticklen=4,
        tickcolor=AXIS,
        tickfont=dict(size=11, color=TEXT_MUTED),
        nticks=5,
    )

    return fig
