"""
results.py — result dataclasses returned by qic(), paretochart(), and bchart().
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go


@dataclass(frozen=True)
class SPCResult:
    """
    Immutable result of a qic() call.

    Fields
    ------
    data       : DataFrame with columns x, y, cl, ucl, lcl, sigma_signal,
                 runs_signal, baseline, excluded
    chart_type : "run", "i", "mr", "p", "u", "c", etc.
    method     : run-signal detection method ("anhoej", "ihi", "weco", "nelson")
    summary    : audit dict — n_obs, longest_run, n_crossings, thresholds, etc.
    signals    : True if any non-random variation detected
    title      : chart title
    subtitle   : optional subtitle
    caption    : optional caption
    ylab       : y-axis label
    xlab       : x-axis label
    """

    data: pd.DataFrame
    chart_type: str
    method: str
    summary: dict[str, Any]
    signals: bool
    title: str
    subtitle: str | None = None
    caption: str | None = None
    ylab: str = ""
    xlab: str = ""
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        """Render as a Plotly Figure. Keyword args override stored display options."""
        from qikit.render.spc_plots import plot_result

        opts = {**self._plot_opts, **overrides}
        return plot_result(self, **opts)

    def show_summary(self) -> None:
        """Print a text summary of the SPC analysis."""
        from .api import _print_summary

        _print_summary(self.chart_type, self.summary)

    def summary_table(self) -> pd.DataFrame:
        """Return a formatted DataFrame of the SPC results."""
        df = self.data.copy()

        # Determine signals
        signals = []
        for s, r in zip(df["sigma_signal"], df["runs_signal"]):
            if s and r:
                signals.append("Both")
            elif s:
                signals.append("Sigma")
            elif r:
                signals.append("Run")
            else:
                signals.append("")

        df["signal_type"] = signals

        # Reorder and pick key columns
        cols = ["x", "y", "cl", "ucl", "lcl", "signal_type"]
        if "part" in df.columns:
            cols.insert(1, "part")
        if "notes" in df.columns:
            cols.append("notes")

        return df[cols]

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
            "subtitle": self.subtitle,
            "caption": self.caption,
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
        return f"SPCResult(chart={self.chart_type!r}, n={n}, method={self.method!r}, {sig})"


@dataclass(frozen=True)
class ParetoResult:
    """Result of a paretochart() call."""
    data: pd.DataFrame
    title: str
    subtitle: str | None = None
    caption: str | None = None
    ylab: str = ""
    xlab: str = ""
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        from qikit.render.spc_plots import plot_pareto
        opts = {**self._plot_opts, **overrides}
        return plot_pareto(self, **opts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        rows = []
        for _, row in self.data.iterrows():
            rows.append({k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in row.items()})
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "caption": self.caption,
            "ylab": self.ylab,
            "xlab": self.xlab,
            "data": rows,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return f"ParetoResult(n_categories={len(self.data)})"


@dataclass(frozen=True)
class BChartResult:
    """Result of a bchart() call."""
    data: pd.DataFrame
    target: float
    or_ratio: float
    limit: float
    title: str
    subtitle: str | None = None
    caption: str | None = None
    ylab: str = ""
    xlab: str = ""
    _plot_opts: dict[str, Any] = field(default_factory=dict, repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        from qikit.render.spc_plots import plot_bchart
        opts = {**self._plot_opts, **overrides}
        return plot_bchart(self, **opts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        rows = []
        for _, row in self.data.iterrows():
            rows.append({k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in row.items()})
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "caption": self.caption,
            "ylab": self.ylab,
            "xlab": self.xlab,
            "target": self.target,
            "or_ratio": self.or_ratio,
            "limit": self.limit,
            "data": rows,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return f"BChartResult(n_obs={len(self.data)}, target={self.target:.3f})"
