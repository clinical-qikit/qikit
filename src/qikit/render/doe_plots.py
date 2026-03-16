"""
experiment_render.py — Plotly rendering for experimental designs in qikit.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..doe import ExperimentResult
from .utils import apply_tufte_theme, NORMAL, CL, SIGMA

ChartType = Literal[
    "effects", "interaction", "cube", "run_order", 
    "timeseries", "dot_diagram", "single_factor",
    "line_effects", "extended_cube"
]

def plot_experiment(result: ExperimentResult, chart_type: ChartType = "effects", **kwargs: Any) -> go.Figure:
    """
    Dispatch to specific experimental design plotting functions.
    """
    if chart_type == "effects":
        return _plot_effects(result, **kwargs)
    elif chart_type == "interaction":
        return _plot_interaction(result, **kwargs)
    elif chart_type == "cube":
        return _plot_cube(result, **kwargs)
    elif chart_type == "run_order":
        return _plot_run_order(result, **kwargs)
    elif chart_type == "timeseries":
        return _plot_timeseries(result, **kwargs)
    elif chart_type == "dot_diagram":
        return _plot_dot_diagram(result, **kwargs)
    elif chart_type == "single_factor":
        return _plot_single_factor(result, **kwargs)
    elif chart_type == "line_effects":
        return _plot_line_effects(result, **kwargs)
    elif chart_type == "extended_cube":
        return _plot_extended_cube(result, **kwargs)
    else:
        # Check if the user is using the old 'doe' terminology in the error message for helpfulness
        raise ValueError(f"Unknown experiment chart type: {chart_type!r}")


def _plot_effects(result: ExperimentResult, **kwargs: Any) -> go.Figure:
    """Horizontal lollipop of abs(effect), sorted largest first."""
    df = result.effects.sort_values("abs_effect", ascending=True)
    
    fig = go.Figure()
    
    # Add lines
    for i, row in df.iterrows():
        fig.add_trace(go.Scatter(
            x=[0, row["abs_effect"]],
            y=[row["term"], row["term"]],
            mode="lines",
            line=dict(color=NORMAL, width=1),
            hoverinfo="skip"
        ))
        
    # Add points
    fig.add_trace(go.Scatter(
        x=df["abs_effect"],
        y=df["term"],
        mode="markers",
        marker=dict(size=10, color=SIGMA),
        hovertemplate="Term: %{y}<br>Abs Effect: %{x:.4f}<extra></extra>"
    ))
    
    fig.update_layout(
        title=dict(text=f"Pareto Chart of Effects (R²={result.r_squared:.3f})", font=dict(size=14)),
        xaxis_title="Absolute Effect",
        yaxis_title="Term",
        showlegend=False
    )
    
    return apply_tufte_theme(fig)


def _plot_interaction(result: ExperimentResult, factors: tuple[int, int] | None = None, **kwargs: Any) -> go.Figure:
    """Interaction plot for two factors."""
    if factors is None:
        factors = (0, 1)
        
    f1_name = result.design.factors[factors[0]]
    f2_name = result.design.factors[factors[1]]
    
    df = result.design.matrix.copy()
    df["Response"] = result.response
    
    means = df.groupby([f1_name, f2_name])["Response"].mean().reset_index()
    
    fig = go.Figure()
    
    # Factor 2 low (-1)
    low_data = means[means[f2_name] == -1]
    fig.add_trace(go.Scatter(
        x=low_data[f1_name],
        y=low_data["Response"],
        mode="lines+markers",
        name=f"{f2_name} Low (-1)",
        line=dict(color=NORMAL, width=1.5),
        marker=dict(size=8)
    ))
    
    # Factor 2 high (1)
    high_data = means[means[f2_name] == 1]
    fig.add_trace(go.Scatter(
        x=high_data[f1_name],
        y=high_data["Response"],
        mode="lines+markers",
        name=f"{f2_name} High (+1)",
        line=dict(color=SIGMA, width=1.5),
        marker=dict(size=8)
    ))
    
    fig.update_layout(
        title=dict(text=f"Interaction Plot: {f1_name} and {f2_name}", font=dict(size=14)),
        xaxis=dict(
            title=f1_name,
            tickmode="array",
            tickvals=[-1, 1],
            ticktext=["Low (-1)", "High (+1)"]
        ),
        yaxis_title="Mean Response",
        showlegend=True,
        legend=dict(x=1.02, y=1, xanchor="left")
    )
    
    return apply_tufte_theme(fig)


def _plot_cube(result: ExperimentResult, **kwargs: Any) -> go.Figure:
    """3D Cube plot for up to 3 factors."""
    k = min(3, result.design.n_factors)
    factors = result.design.factors[:k]
    
    df = result.design.matrix.copy()
    df["Response"] = result.response
    means = df.groupby(list(factors))["Response"].mean().reset_index()
    
    if k < 3:
        # Fallback to 2D square if only 2 factors
        fig = go.Figure()
        fig.add_annotation(text="2D Cube plot coming soon", x=0.5, y=0.5, showarrow=False)
        return apply_tufte_theme(fig)

    # 3D Cube using Scatter3d
    # 8 vertices of the cube
    fig = go.Figure()
    
    # Draw edges
    edges = [
        ([ -1, 1], [-1, -1], [-1, -1]), ([ -1, 1], [ 1,  1], [-1, -1]),
        ([ -1, 1], [-1, -1], [ 1,  1]), ([ -1, 1], [ 1,  1], [ 1,  1]),
        ([-1, -1], [ -1, 1], [-1, -1]), ([ 1,  1], [ -1, 1], [-1, -1]),
        ([-1, -1], [ -1, 1], [ 1,  1]), ([ 1,  1], [ -1, 1], [ 1,  1]),
        ([-1, -1], [-1, -1], [ -1, 1]), ([ 1,  1], [-1, -1], [ -1, 1]),
        ([-1, -1], [ 1,  1], [ -1, 1]), ([ 1,  1], [ 1,  1], [ -1, 1]),
    ]
    
    for ex, ey, ez in edges:
        fig.add_trace(go.Scatter3d(
            x=ex, y=ey, z=ez,
            mode="lines",
            line=dict(color=NORMAL, width=2),
            hoverinfo="skip"
        ))
        
    # Add vertices with response labels
    fig.add_trace(go.Scatter3d(
        x=means[factors[0]],
        y=means[factors[1]],
        z=means[factors[2]],
        mode="markers+text",
        marker=dict(size=5, color=SIGMA),
        text=means["Response"].round(2),
        textposition="top center",
        hovertemplate=f"{factors[0]}: %{{x}}<br>{factors[1]}: %{{y}}<br>{factors[2]}: %{{z}}<br>Mean: %{{text}}<extra></extra>"
    ))
    
    fig.update_layout(
        title=f"Cube Plot: {', '.join(factors)}",
        scene=dict(
            xaxis_title=factors[0],
            yaxis_title=factors[1],
            zaxis_title=factors[2],
            xaxis=dict(tickvals=[-1, 1]),
            yaxis=dict(tickvals=[-1, 1]),
            zaxis=dict(tickvals=[-1, 1]),
        ),
        showlegend=False
    )
    
    return fig # apply_tufte_theme doesn't apply well to 3D


def _plot_run_order(result: ExperimentResult, **kwargs: Any) -> go.Figure:
    """Response vs run order scatter."""
    df = result.design.matrix.copy()
    df["Response"] = result.response
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["RunOrder"],
        y=df["Response"],
        mode="lines+markers",
        line=dict(color=NORMAL, width=1),
        marker=dict(color=SIGMA, size=8),
        hovertemplate="Run: %{x}<br>Response: %{y}<extra></extra>"
    ))
    
    fig.update_layout(
        title=dict(text="Response vs Run Order", font=dict(size=14)),
        xaxis_title="Run Order",
        yaxis_title="Response"
    )
    return apply_tufte_theme(fig)


def _plot_timeseries(result: ExperimentResult, **kwargs: Any) -> go.Figure:
    """Delegates to qic(y=response, chart='i')."""
    from qikit import qic
    spc = qic(y=result.response, chart="i", title="Experimental Response Time Series")
    return spc.plot()


def _plot_dot_diagram(result: ExperimentResult, **kwargs: Any) -> go.Figure:
    """Horizontal strip of all response values."""
    fig = go.Figure()
    fig.add_trace(go.Box(
        x=result.response,
        boxpoints="all",
        jitter=0.3,
        pointpos=-1.8,
        name="",
        marker=dict(color=SIGMA, size=6),
        line=dict(color=NORMAL, width=1),
        fillcolor="rgba(255,255,255,0)"
    ))
    
    fig.update_layout(
        title=dict(text="Dot Diagram of Responses", font=dict(size=14)),
        xaxis_title="Response",
        showlegend=False
    )
    return apply_tufte_theme(fig)


def _plot_single_factor(result: ExperimentResult, factor: int = 0, **kwargs: Any) -> go.Figure:
    """Mean response at each level for 1 factor."""
    f_name = result.design.factors[factor]
    df = result.design.matrix.copy()
    df["Response"] = result.response
    means = df.groupby(f_name)["Response"].mean().reset_index()
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=means[f_name],
        y=means["Response"],
        mode="lines+markers",
        line=dict(color=SIGMA, width=2),
        marker=dict(size=10)
    ))
    
    fig.update_layout(
        title=dict(text=f"Main Effect: {f_name}", font=dict(size=14)),
        xaxis=dict(
            tickmode="array",
            tickvals=[-1, 1],
            ticktext=["Low (-1)", "High (+1)"]
        ),
        yaxis_title="Mean Response"
    )
    return apply_tufte_theme(fig)


def _plot_line_effects(result: ExperimentResult, **kwargs: Any) -> go.Figure:
    """Response vs Design Order."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        y=result.response,
        mode="lines+markers",
        line=dict(color=NORMAL, width=1),
        marker=dict(color=SIGMA, size=8)
    ))
    
    fig.update_layout(
        title=dict(text="Response in Standard (Yates) Order", font=dict(size=14)),
        xaxis_title="Standard Order Index",
        yaxis_title="Response"
    )
    return apply_tufte_theme(fig)


def _plot_extended_cube(result: ExperimentResult, **kwargs: Any) -> go.Figure:
    """Cube plot with data labels."""
    return _plot_cube(result, **kwargs)
