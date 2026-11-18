"""
pareto.py — Pareto and Bernoulli CUSUM figures.
"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .layout import _CAPTION_TOP
from .theme import AXIS, CL, GRID, NORMAL, SIGMA, TEXT, TEXT_FAINT, apply_tufte_theme


def plot_pareto(result, title: str = "", subtitle: str | None = None, caption: str | None = None,
                xlab: str | None = None, ylab: str = "Frequency", x_angle: int | None = None,
                width: int | None = None, height: int | None = None) -> go.Figure:
    """Bars by frequency with the cumulative percentage on a second axis."""
    df = result.data
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=df["category"], y=df["count"], name=ylab, marker_color=NORMAL,
                         hovertemplate="%{x}: %{y}<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=df["category"], y=df["cum_percent"], name="Cumulative %",
                             mode="lines+markers", line=dict(color=SIGMA, width=2),
                             marker=dict(size=6), hovertemplate="%{x}: %{y:.1f}%<extra></extra>"),
                  secondary_y=True)
    _simple_layout(fig, title, subtitle, caption,
                   xlab if xlab is not None else (result.summary.get("x_name") or ""), ylab,
                   width, height)
    fig.update_layout(yaxis2_title="Cumulative %")
    fig.update_yaxes(range=[0, df["count"].sum() * 1.05], secondary_y=False)
    fig.update_yaxes(range=[0, 105], ticksuffix="%", secondary_y=True)
    if x_angle is not None:
        fig.update_xaxes(tickangle=x_angle)
    return fig


def plot_bchart(result, title: str = "", subtitle: str | None = None, caption: str | None = None,
                xlab: str = "Case #", ylab: str = "CUSUM", width: int | None = None,
                height: int | None = None) -> go.Figure:
    """The upward and downward Bernoulli CUSUMs against their decision limits."""
    df, limit = result.data, result.summary["limit"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["x"], y=df["cusum_up"], mode="lines",
                             line=dict(color=NORMAL, width=1.5), name="CUSUM up",
                             hovertemplate="Case %{x}<br>CUSUM up: %{y:.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=df["x"], y=df["cusum_down"], mode="lines",
                             line=dict(color=NORMAL, width=1.5, dash="dot"), name="CUSUM down",
                             hovertemplate="Case %{x}<br>CUSUM down: %{y:.2f}<extra></extra>"))
    for col, level, symbol, name in (("signal_up", limit, "triangle-up", "Signal up"),
                                     ("signal_down", -limit, "triangle-down", "Signal down")):
        hits = df[df[col]]
        if not hits.empty:
            fig.add_trace(go.Scatter(x=hits["x"], y=[level] * len(hits), mode="markers",
                                     marker=dict(color=SIGMA, size=10, symbol=symbol),
                                     name=name, hoverinfo="skip"))
    for level, dash in ((limit, "dash"), (-limit, "dash"), (0, None)):
        fig.add_hline(y=level, line=dict(color=CL, width=1, **({"dash": dash} if dash else {})))
    _simple_layout(fig, title or f"Bernoulli CUSUM (p0 = {result.summary['target']:.3f}, "
                   f"OR = {result.summary['or_ratio']:g})", subtitle, caption, xlab, ylab,
                   width, height)
    return fig


def _simple_layout(fig, title, subtitle, caption, xlab, ylab, width, height) -> None:
    text = title + (f"<br><sup>{subtitle}</sup>" if subtitle else "")
    size = {k: v for k, v in (("width", width), ("height", height)) if v is not None}
    fig.update_layout(title=dict(text=text, font=dict(size=15, color=TEXT), x=0, xanchor="left"),
                      xaxis_title=xlab, yaxis_title=ylab, margin=dict(l=50, r=50, t=60, b=80),
                      **size)
    apply_tufte_theme(fig)
    if caption:
        fig.add_annotation(text=caption, xref="paper", yref="paper", x=0, y=0,
                           yshift=-_CAPTION_TOP, yanchor="top", showarrow=False,
                           font=dict(size=10, color=TEXT_FAINT), xanchor="left")
    fig.update_xaxes(showline=True, linecolor=AXIS)
    fig.update_yaxes(showgrid=True, gridcolor=GRID)
