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
    data       : one row per plotted point. Always present:
                   x, y                  — the point (y after multiply=)
                   cl, ucl, lcl          — center line and outer limits (3σ; the
                                           99.8% contour on oe/oep)
                   ucl_95, lcl_95        — inner band (2σ; the 95% contour on oe/oep)
                   sigma_signal          — beyond ucl/lcl
                   runs_signal           — flagged by the runs method (all False on
                                           a funnel)
                   runs_signal_localized — runs_signal without the Anhoej crossings
                                           whole-series blanket
                   baseline              — point is in the limit baseline
                   excluded              — point was ghosted by exclude=
                 Present only when relevant:
                   warn_signal           — beyond ucl_95/lcl_95 but not a
                                           sigma_signal, so the two tiers never
                                           overlap; excluded points are always
                                           False. On oe/oep, and on p/pp/u/up with
                                           funnel=True. Not counted in `signals`.
                   notes, label, target, part, facet — from the matching qic()
                                           argument (label from point_labels=)
                   <hover_extra names>   — copied from hover_extra=
                   min_detectable_oe     — oe/oep: smallest O/E this point could
                                           have flagged at 80% power (y scale)
                   ci_95_lower, ci_95_upper — oe/oep: exact Garwood 95% CI on the
                                           point's own O/E (y scale)
                   observed, expected    — oe/oep: event counts, echoed in plotted
                                           (post-funnel-sort) order
    chart_type : "run", "i", "mr", "p", "u", "c", etc.
    method     : run-signal detection method ("anhoej", "ihi", "weco", "nelson")
    summary    : audit dict. Always: n_obs, n_baseline, signals, limit_basis,
                 freeze, excluded, plus the runs method's own keys (longest_run,
                 n_crossings, thresholds, …; runs_disabled/note on a funnel).
                 n_warn — count of warn_signal points, wherever that column exists.
                 O/E charts add:
                   limit_method        — oe only: "exact" or "byar"
                   dispersion_phi      — oep only: Spiegelhalter's winsorized
                                         multiplicative over-dispersion factor φ̂.
                                         Dimensionless (a variance ratio against
                                         Poisson). Set to 1.0 when the sample is
                                         within 2 SE of Poisson; never below 1.0.
                                         The limits are widened by √φ̂.
                   dispersion_adjusted — oep only: φ̂ > 1.0, i.e. the limits were
                                         actually widened
                   min_detectable_oe_median — median of min_detectable_oe over
                                         non-excluded points (raw O/E scale)
                   n_underpowered      — points that could not detect a doubling
                                         of risk (min_detectable_oe > 2.0)
                   underpowered        — min_detectable_oe_median > 2.0: a blank
                                         funnel here means "not enough data"
                   power_note          — one-sentence caveat, present only when
                                         underpowered
                 The last four are omitted when no point has a finite expected
                 count.
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
        """
        Render as a Plotly Figure. Keyword args override stored display options.

        Trace names are a stable public contract, for callers who restyle the
        figure: "data" (the points), "Target", "CL", the outer limits "UCL"/"LCL"
        ("99.8%+"/"99.8%-" on oe/oep), and the inner band, drawn with
        show_95=True, "2σ+"/"2σ-" ("95%+"/"95%-" on oe/oep). The layout of the
        data trace's customdata and hovertemplate is not part of that contract;
        use point_labels= and hover_extra= on qic() to change what the tooltip says.
        """
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

        if "warn_signal" in df.columns:
            signals = ["Warn" if (w and not sig) else sig for w, sig in zip(df["warn_signal"], signals)]

        df["signal_type"] = signals

        # Reorder and pick key columns
        cols = ["x", "y", "cl", "ucl", "lcl", "signal_type"]
        if "label" in df.columns:
            cols.insert(1, "label")
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
