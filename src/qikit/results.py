"""
results.py — what qic(), funnel(), paretochart() and bchart() return.

Each result is a frozen dataclass whose .data is a plain DataFrame (one row per point
or provider, ready to write back to a table) and whose .summary is a plain dict. The
figure is drawn on demand by .plot(), which is the only place plotly is imported.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import plotly.graph_objects as go

# Geometric steps between a funnel's smallest and largest denominator for its contours;
# every provider's own denominator is added, so each curve passes through the limit that
# decided that provider's signal.
_GRID_STEPS = 200


def _require_plotly() -> None:
    """Figures need plotly, an optional extra so that analysis alone installs less."""
    try:
        import plotly  # noqa: F401
    except ImportError as err:
        raise ImportError(
            "Drawing a figure needs plotly: pip install 'clinical-qikit[plot]'. The "
            "analysis itself (.data, .summary) does not."
        ) from err


def _plain(v: Any) -> Any:
    """A JSON-safe value: NaN and NA become None, numpy scalars plain Python."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if math.isnan(v) else float(v)
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(v).isoformat())
    return v


class _Serializable:
    data: pd.DataFrame
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """{"data": [one dict per row], "summary": {...}}, JSON-safe (NaN becomes None)."""
        rows = [{k: _plain(v) for k, v in row.items()}
                for row in self.data.to_dict(orient="records")]
        return {"data": rows, "summary": _plain(self.summary)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass(frozen=True)
class SPCResult(_Serializable):
    """
    What qic() returns. data: one row per point (qic's docstring lists every column);
    summary: what the rules found and how the limits were set. plot(**options) draws it.
    """

    data: pd.DataFrame
    summary: dict[str, Any]
    chart: str
    method: str
    _meta: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def signals(self) -> bool:
        """Whether any point is an outlier or any rule found a pattern."""
        return bool(self.summary.get("signals"))

    def plot(self, **options: Any) -> "go.Figure":
        """
        A Plotly figure. Options: title, subtitle, caption, xlab, ylab, show_95,
        show_labels, show_grid, show_x_labels, label_signals ("outlier"), runs_highlight
        ("localized", "all", "none"), styles (restyle by role), x_range, y_range, x_order,
        x_format, x_angle, y_percent, y_neg, y_expand, decimals, point_size, connect,
        show_legend, flip, width, height, and nrow, ncol, scales for facets.
        An unknown name raises TypeError.
        """
        _require_plotly()
        from .plot.charts import plot_spc

        return plot_spc(self, **options)

    def __repr__(self) -> str:
        sig = "signals" if self.signals else "no signal"
        return f"SPCResult(chart={self.chart!r}, method={self.method!r}, n={len(self.data)}, {sig})"

    def __str__(self) -> str:
        s = self.summary
        lines = [f"{self.chart} chart, {s.get('n_obs', len(self.data))} points, "
                 f"rules: {self.method}"]

        def one(p: dict, prefix: str = "") -> str:
            text = f"{prefix}{p.get('n_outlier', 0)} beyond the limits"
            if "longest_run" in p:
                text += (f"; longest run {p['longest_run']} (more than "
                         f"{p['longest_run_max']} signals); {p['n_crossings']} crossings "
                         f"(fewer than {p['n_crossings_min']} signals)")
            elif p.get("rules_fired"):
                text += "; rules fired: " + ", ".join(p["rules_fired"])
            if p.get("variation"):
                text += f"; latest point: {p['variation']}"
            if p.get("assurance"):
                text += f"; assurance: {p['assurance']}"
            return text

        if "by_facet" in s:
            lines += [one(f, f"  {k}: ") for k, f in s["by_facet"].items()]
        else:
            lines.append(one(s))
        lines.append("Signal." if self.signals else "No signal: the process looks stable.")
        return "\n".join(lines)


@dataclass(frozen=True)
class FunnelResult(_Serializable):
    """
    What funnel() returns. data: one row per provider (funnel's docstring lists every
    column); summary: the model, tier counts, expected_false_flags and notes.
    plot(**options) draws it; limits(n=None) gives the contours at any denominators;
    print(result) describes it in a few sentences.
    """

    data: pd.DataFrame
    summary: dict[str, Any]
    _models: dict[Any, dict[str, Any]] = field(default_factory=dict, repr=False)
    _meta: dict[str, Any] = field(default_factory=dict, repr=False)
    # The default contour grid, drawn once: plotting twice reuses it.
    _grid: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False, compare=False)

    def plot(self, **options: Any) -> "go.Figure":
        """
        A Plotly figure against each provider's volume. Options: title, subtitle,
        caption, xlab, ylab, label_signals ("outlier", "alert", "both"), styles (restyle
        by role), x_log, x_range, y_range, show_legend, show_x_labels, width, height, and
        nrow, ncol, scales for facets. An unset caption states the flag rule.
        """
        _require_plotly()
        from .plot.charts import plot_funnel

        return plot_funnel(self, **options)

    def limits(self, n: Any = None) -> pd.DataFrame:
        """
        The contours at any denominators: columns denominator, cl, lower_outlier,
        upper_outlier, lower_alert, upper_alert (on the plotted y scale), plus the facet
        columns. n=None gives the grid the plot draws, which passes through every
        provider's own limits. Under a within_dispersion column the denominator is the
        effective one, the plot's x axis.
        """
        if n is None and "default" in self._grid:
            return self._grid["default"].copy()
        from .core.contours import funnel_contours

        frames = []
        facets = self._meta.get("facets", [])
        for name, model in self._models.items():
            if n is not None:
                grid = np.asarray(n, dtype=float)
            else:
                grid = _funnel_grid(model["axis"], model["family"] == "binomial")
            phi = model["phi"]
            n_model = grid if phi in (None, 1.0) else grid / phi
            lim = funnel_contours(model["family"], model["cl"], n_model, model["tau2"],
                                  model["levels"], model["limit_method"], model["scale"])
            m = model["multiply"]
            frame = pd.DataFrame({
                "denominator": grid, "cl": np.full(len(grid), model["cl"] * m),
                "lower_outlier": lim.lcl * m, "upper_outlier": lim.ucl * m,
                "lower_alert": lim.lcl_95 * m, "upper_alert": lim.ucl_95 * m,
            })
            for i, col in enumerate(facets):
                frame.insert(i, col, model["key"][i])
            frames.append(frame)
        out = pd.concat(frames, ignore_index=True)
        if n is None:
            self._grid["default"] = out
        return out.copy()

    def __repr__(self) -> str:
        s = self.summary
        return (f"FunnelResult(measure={s.get('measure')!r}, providers={s.get('n_providers')}, "
                f"outliers={s.get('n_outlier')}, alerts={s.get('n_alert')})")

    def __str__(self) -> str:
        return _describe(self.summary)


def _funnel_grid(n_obs: np.ndarray, integer: bool) -> np.ndarray:
    """
    Denominators to draw a funnel's contours at: geometric steps across the observed
    range, merged with every observed n. A binomial chart steps in whole numbers, where
    its limits are exact; between them they are interpolated (docs/methods.md §4.13).
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


def _describe(summary: dict) -> str:
    """print(result): what was compared, what flagged, and what a reader must know."""
    rule = (
        f"exact test, outlier beyond the {summary['limits'][0] * 100:g}% contour, alert "
        f"beyond {summary['limits'][1] * 100:g}%"
        if summary["signal"] == "limits"
        else f"false discovery rate, outlier q < {summary['fdr_levels'][0]:g}, "
             f"alert q < {summary['fdr_levels'][1]:g}"
    )
    side = f"worse = {summary['worse']}" if summary["worse"] else "both sides flagged"
    lines = [f"Funnel ({summary['measure']}; {rule}; {side})"]

    def counts(s: dict, prefix: str = "") -> str:
        text = (
            f"{prefix}{s['n_providers']} providers: {s['n_outlier']} outlier, "
            f"{s['n_alert']} alert"
        )
        exp = s.get("expected_false_flags")
        if exp and summary["signal"] == "limits":
            text += f" (expected by chance: {exp['outlier']:g} and {exp['alert']:g})"
        elif exp:
            text += (f" (at most false: {exp['outlier']:g} outliers, "
                     f"{exp['outlier_or_alert']:g} of outliers and alerts)")
        if s.get("tau") is not None and summary["overdispersion"]:
            scale = s.get("tau_scale", "natural")
            on = "" if scale == "natural" else f" on the {scale} scale"
            text += f"; spread between providers tau = {s['tau']:.3g}{on}"
        if s.get("within_dispersion", 1.0) != 1.0:
            text += f"; within_dispersion = {s['within_dispersion']:.3g}"
        b = s.get("benchmark")
        if b is not None:
            if b["method"] == "abc":
                text += (f"; achievable benchmark (ABC) = {b['value']:.4g} from "
                         f"{b['providers']} providers")
            else:
                text += f"; benchmark (shrunk percentile) = {b['value']:.4g}"
        return text

    if "by_facet" in summary:
        for fv, s in summary["by_facet"].items():
            lines.append(counts(s, f"  {fv}: "))
    else:
        lines.append(counts(summary))
    lines += [f"Note: {note}" for note in summary["notes"]]
    return "\n".join(lines)


@dataclass(frozen=True)
class ParetoResult(_Serializable):
    """What paretochart() returns: categories by count, with the cumulative share."""
    data: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)

    def plot(self, **options: Any) -> "go.Figure":
        _require_plotly()
        from .plot.charts import plot_pareto

        return plot_pareto(self, **options)

    def __repr__(self) -> str:
        return f"ParetoResult(n_categories={len(self.data)})"


@dataclass(frozen=True)
class BChartResult(_Serializable):
    """What bchart() returns: the two Bernoulli CUSUMs and where they signalled."""
    data: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)

    def plot(self, **options: Any) -> "go.Figure":
        _require_plotly()
        from .plot.charts import plot_bchart

        return plot_bchart(self, **options)

    def __repr__(self) -> str:
        return f"BChartResult(n_obs={len(self.data)}, target={self.summary.get('target', math.nan):.3f})"
