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

# Geometric steps between a funnel's smallest and largest denominator. Dense enough
# that the contours read as curves at any plot width; every point's own n is added
# on top, so the steps only ever fill in between providers.
_GRID_STEPS = 200


def n_varies(data: pd.DataFrame) -> bool:
    """Whether a funnel's denominators differ, so a volume axis has a range to span."""
    if "n" not in data.columns:
        return False
    vals = data["n"].to_numpy(dtype=float)
    vals = vals[np.isfinite(vals) & (vals > 0)]
    return len(vals) > 0 and float(vals.min()) < float(vals.max())


def _funnel_grid(n_obs: np.ndarray, integer: bool) -> np.ndarray:
    """
    Denominators to draw a funnel's contours at: geometric steps across the observed
    range, merged with every observed n so each curve passes through the limit that
    decided that point's signal. A binomial chart steps in whole numbers, since a
    non-integer n would fall back to the normal approximation.
    """
    n_obs = np.asarray(n_obs, dtype=float)
    n_obs = n_obs[np.isfinite(n_obs) & (n_obs > 0)]
    if len(n_obs) == 0:
        return n_obs
    lo, hi = float(n_obs.min()), float(n_obs.max())
    steps = np.geomspace(lo, hi, _GRID_STEPS) if hi > lo else np.array([lo])
    if integer:
        steps = np.round(steps)
    return np.unique(np.concatenate([steps[steps > 0], n_obs]))


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
                   min_detectable        — p/pp/u/up with funnel=True: smallest
                                           true proportion or rate this point could
                                           have flagged at 80% power (y scale);
                                           NaN where no count can flag
                   ci_95_lower, ci_95_upper — oe/oep: exact Garwood 95% CI on the
                                           point's own O/E; p/u funnels: Clopper–
                                           Pearson (p, pp) or Garwood (u, up) on
                                           its own proportion or rate (y scale)
                   observed, expected    — oe/oep: event counts, echoed in plotted
                                           (post-funnel-sort) order
                   n                     — every chart with denominators (ip, p,
                                           pp, u, up, oe, oep): the denominator in
                                           plotted order, never scaled by multiply;
                                           expected events on oe/oep, where it
                                           equals `expected`
    chart_type : "run", "i", "mr", "p", "u", "c", etc.
    method     : run-signal detection method ("anhoej", "ihi", "weco", "nelson")
    summary    : audit dict. Always: n_obs, n_baseline, signals, limit_basis,
                 freeze, excluded, plus the runs method's own keys (longest_run,
                 n_crossings, thresholds, …; runs_disabled/note on a funnel).
                 n_warn — count of warn_signal points, wherever that column exists.
                 Funnels (p/pp/u/up with funnel=True) and oe/oep add:
                   limit_method        — "exact", or "byar" on an oe chart that
                                         asked for it, or "normal" if any point
                                         fell back to the normal approximation
                                         (a non-integer denominator, say)
                   dispersion_phi      — Spiegelhalter's 10%-winsorized dispersion
                                         ratio φ̂ (Stat Med 2005, eqs. 6, 8), as
                                         published: averages ~0.68 under chance
                   dispersion_tau      — τ̂, the SD of providers' true rates (or
                                         true O/E) around the center line beyond
                                         what chance explains, on the raw scale;
                                         0.0 when φ̂ < (K−1)/K
                   overdispersed       — τ̂ > 0
                   dispersion_note     — unadjusted charts (p/u/oe), only when
                                         overdispersed: one quotable sentence
                   dispersion_method   — "additive" on pp/up funnels and oep;
                                         "laney" on time-ordered pp/up
                   dispersion_adjusted — adjusted charts only: τ̂ > 0, i.e. the
                                         limits actually moved
                 docs/methods.md records the method behind each of these.
                 O/E charts also add:
                   min_detectable_oe_median — median of min_detectable_oe over
                                         non-excluded points (raw O/E scale)
                   n_underpowered      — points that could not detect a doubling
                                         of risk (min_detectable_oe > 2.0)
                   underpowered        — min_detectable_oe_median > 2.0: a blank
                                         funnel here means "not enough data"
                   power_note          — one-sentence caveat, present only when
                                         underpowered
                 The last four are omitted when no point has a finite expected
                 count. p/pp/u/up funnels add n_underpowered, underpowered and
                 power_note on the same terms, judged relative to the center line
                 (min_detectable / cl > 2.0, unflaggable points included), plus:
                   min_detectable_ratio_median — median of min_detectable / cl over
                                         non-excluded points; null when most
                                         points cannot flag at all
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
    # What funnel_limits() needs to redraw the limits off the points: per facet value
    # (None when unfaceted), the raw chart, cl, tau2 and limit_method, and multiply.
    # None on charts without funnel contours.
    _funnel: dict[Any, dict[str, Any]] | None = field(default=None, repr=False)

    def plot(self, **overrides: Any) -> go.Figure:
        """
        Render as a Plotly Figure. Keyword args override stored display options.

        Trace names are a stable public contract, for callers who restyle the
        figure: "data" (the points), "Target", "CL", the outer limits "UCL"/"LCL"
        ("99.8%+"/"99.8%-" on funnels and oe/oep), and the inner band, drawn with
        show_95=True, "2σ+"/"2σ-" ("95%+"/"95%-" there). On a volume axis
        (x_spacing="n", a funnel's default) the limit traces are drawn on the
        funnel_limits() grid rather than at the points, so do not assume they have
        one value per point. The layout of the data trace's customdata and
        hovertemplate is not part of that contract; use point_labels= and
        hover_extra= on qic() to change what the tooltip says.
        """
        from qikit.render.spc_plots import plot_result

        opts = {**self._plot_opts, **overrides}
        return plot_result(self, **opts)

    def funnel_limits(self, n: Any = None) -> pd.DataFrame:
        """
        The funnel's limits at any denominators, for drawing its contours.

        n=None gives the grid a volume-axis plot draws: about 200 geometric steps
        between the smallest and largest denominator, plus every point's own n, so
        each curve passes exactly through the limit that decided that point's
        signal. Pass n= (a sequence) to evaluate elsewhere. Denominators are those
        of n=: expected events on oe/oep, the sample size or exposure on p/pp/u/up.

        Returns columns n, cl, ucl, lcl, ucl_95, lcl_95 on the y scale (multiply=
        applied, as in result.data), sorted by n for the default grid, plus facet on
        a faceted result. Available on oe/oep and on p/pp/u/up with funnel=True.
        """
        if not self._funnel:
            raise ValueError(
                "funnel_limits() needs funnel contours: chart='oe'/'oep', or "
                "chart='p'/'pp'/'u'/'up' with funnel=True."
            )
        from .compute import funnel_limits

        frames = []
        for facet, params in self._funnel.items():
            if n is not None:
                grid = np.asarray(n, dtype=float)
            else:
                rows = self.data if facet is None else self.data[self.data["facet"] == facet]
                grid = _funnel_grid(rows["n"].to_numpy(dtype=float), params["chart"] in ("p", "pp"))
            lim = funnel_limits(
                params["chart"], params["cl"], grid,
                tau2=params["tau2"], limit_method=params["limit_method"],
            )
            scale = params["multiply"]
            frame = pd.DataFrame({
                "n": grid,
                "cl": np.full(len(grid), params["cl"]) * scale,
                **{k: v * scale for k, v in lim.items()},
            })
            if facet is not None:
                frame["facet"] = facet
            frames.append(frame)
        return pd.concat(frames, ignore_index=True)

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
