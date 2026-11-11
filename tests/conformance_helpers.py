"""
The engine contract the shared fixtures speak, on top of qikit's public API.

fixtures/spc/*.json are run by both engines: this Python package and the TypeScript
engine of the Excel add-in (excel-addin/packages/engine), which keeps the original
engine vocabulary (chart="oe", funnel=True, sigma_signal, warn_signal, ucl, ...).
engine_qic() takes that vocabulary, calls qic() or funnel(), and returns a result in
it, so the fixtures, their snapshots, and the numeric tests written against the engine
keep checking the same numbers. It is a test adapter, not part of the package.
"""

from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from qikit import bchart, design, paretochart, qic
from qikit.core.dispersion import DEFAULT_TAU_METHOD
from qikit.funnel import _funnel, _normalize, _settings

_FUNNEL_CHARTS = {"oe": ("oe", False), "oep": ("oe", True), "p": ("proportion", False),
                  "pp": ("proportion", True), "u": ("rate", False), "up": ("rate", True)}
_WORSE = {"both": None, "above": "higher", "below": "lower"}
_DISPLAY = {
    "title", "subtitle", "caption", "xlab", "ylab", "part_labels", "show_labels", "show_95",
    "show_grid", "show_x_labels", "decimals", "point_size", "x_format", "x_angle", "x_pad",
    "x_order", "y_expand", "height", "width", "y_neg", "y_percent", "y_percent_accuracy",
    "connect", "runs_highlight", "label_signals", "x_range", "y_range", "styles",
    "show_legend", "flip", "strip_horizontal", "nrow", "ncol", "scales", "x_spacing",
    "x_log", "print_summary",
}


@dataclass
class EngineResult:
    """A result in the engine vocabulary: data, summary, signals, and its own to_dict."""
    data: pd.DataFrame
    summary: dict[str, Any]
    chart_type: str
    method: str
    public: Any = field(repr=False, default=None)
    plot_options: dict = field(repr=False, default_factory=dict)

    @property
    def signals(self) -> bool:
        return bool(self.summary.get("signals"))

    def plot(self, **overrides):
        return self.public.plot(**{**self.plot_options, **overrides})

    def funnel_limits(self, n=None) -> pd.DataFrame:
        """The public limits() in engine names: n, cl, ucl, lcl, ucl_95, lcl_95, facet."""
        if not hasattr(self.public, "limits"):
            raise ValueError("funnel_limits() needs funnel contours.")
        lim = self.public.limits(n)
        out = pd.DataFrame({
            "n": lim["denominator"], "cl": lim["cl"], "ucl": lim["upper_outlier"],
            "lcl": lim["lower_outlier"], "ucl_95": lim["upper_alert"], "lcl_95": lim["lower_alert"],
        })
        facets = self.public._meta.get("facets") or []
        if facets:
            out["facet"] = lim[facets[0]].to_numpy()
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def to_dict(self) -> dict[str, Any]:
        def safe(v):
            if isinstance(v, dict):
                return {str(k): safe(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [safe(x) for x in v]
            if isinstance(v, (np.bool_,)):
                return bool(v)
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, (float, np.floating)):
                return None if math.isnan(v) else float(v)
            if v is pd.NA:
                return None
            return v
        rows = [{k: safe(v) for k, v in row.items()} for row in self.data.to_dict("records")]
        return {"chart_type": self.chart_type, "method": self.method, "signals": self.signals,
                "summary": safe(self.summary), "data": rows}


def engine_qic(
    x=None, y=None, n=None, data=None, chart="run", funnel=False, cl=None, exclude=None,
    limit_method=None, tau_method=None, signal_side="both", signal_method="limits",
    levels=(0.998, 0.95), fdr_levels=(0.05, 0.10), multiply=1.0, method="anhoej",
    freeze=None, part=None, notes=None, target=None, point_labels=None, hover_extra=None,
    facets=None, agg_fun="mean", x_period=None, within_dispersion=1.0, tau_fixed=None,
    test_min_expected=None, **display,
) -> EngineResult:
    unknown = set(display) - _DISPLAY
    if unknown:
        raise TypeError(f"engine_qic() got unexpected keyword argument(s) {sorted(unknown)}")
    chart = chart.lower().strip()
    plot_options = {k: v for k, v in display.items() if k in _PLOT_PASS}
    is_funnel = chart in ("oe", "oep") or funnel
    _check_engine(chart, is_funnel, n, freeze, part, limit_method, signal_side,
                  signal_method, levels, hover_extra)
    if is_funnel:
        return _engine_funnel(
            chart, x, y, n, data, cl, exclude, limit_method, tau_method, signal_side,
            signal_method, levels, fdr_levels, multiply, point_labels, hover_extra, facets,
            within_dispersion, tau_fixed, test_min_expected, plot_options,
        )
    return _engine_series(chart, x, y, n, data, cl, exclude, multiply, method, freeze, part,
                          notes, target, point_labels, hover_extra, facets, agg_fun,
                          x_period, plot_options)


_PLOT_PASS = {"title", "subtitle", "caption", "xlab", "ylab", "show_labels", "show_95",
              "show_grid", "show_x_labels", "decimals", "point_size", "x_format", "x_angle",
              "x_order", "y_expand", "height", "width", "y_neg", "y_percent", "connect",
              "runs_highlight", "styles", "x_range", "y_range", "show_legend", "flip",
              "nrow", "ncol", "scales"}


def _engine_series(chart, x, y, n, data, cl, exclude, multiply, method, freeze, part, notes,
                   target, point_labels, hover_extra, facets, agg_fun, x_period, plot_options):
    # The engine's part= gave the point where each part starts; qic's gives where one ends.
    if part is not None and not isinstance(part, str):
        part = [p - 1 for p in ([part] if isinstance(part, (int, np.integer)) else part)]
    r = qic(data, x=x, y=y, n=n, chart=chart, method=method, freeze=freeze, part=part,
            exclude=exclude, center=cl, target=target, agg_fun=agg_fun, x_period=x_period,
            multiply=multiply, facets=facets, label=point_labels,
            hover=hover_extra, notes=notes)
    d = r.data.copy()
    out = pd.DataFrame({"x": d["x"]})
    for col in ("label",):
        if col in d:
            out[col] = d[col]
    for col in ("y", "cl", "ucl", "lcl", "ucl_95", "lcl_95"):
        out[col] = d[col]
    out["sigma_signal"] = d["signal"] == "outlier"
    blanket = _crossings_blanket(r, d)
    out["runs_signal"] = d["runs_signal"] | blanket
    out["runs_signal_localized"] = d["runs_signal"]
    out["baseline"] = d["baseline"]
    out["excluded"] = d["excluded"]
    for col in ("n", "notes", "target", "part"):
        if col in d:
            out[col] = d[col]
    if facets is not None:
        out["facet"] = d[facets]
    for col in ([hover_extra] if isinstance(hover_extra, str) else list(hover_extra or [])):
        if col in d:
            out[col] = d[col]
    if chart == "mr":
        out = out.iloc[1:].reset_index(drop=True)
    # notes and provisional are the front door's words to a reader, not engine numbers,
    # so they stay out of the fixtures the TypeScript engine conforms to.
    s = {k: v for k, v in r.summary.items() if k not in ("notes", "provisional")}
    if "rules_fired" in s:
        s["shift_signal"] = any(name.startswith("shift") for name in s["rules_fired"])
        s["trend_signal"] = any(name.startswith("trend") for name in s["rules_fired"])
    return EngineResult(out, s, chart, method, public=r, plot_options=plot_options)


_ENGINE_RESERVED = {
    "x", "y", "cl", "ucl", "lcl", "ucl_95", "lcl_95", "sigma_signal", "warn_signal",
    "runs_signal", "runs_signal_localized", "baseline", "excluded", "notes", "label",
    "target", "part", "facet", "min_detectable_oe", "min_detectable", "ci_95_lower",
    "ci_95_upper", "observed", "expected", "n", "p_value", "q_value",
}


def _check_engine(chart, is_funnel, n, freeze, part, limit_method, side, method, levels,
                  hover_extra):
    """The argument checks the engine made, which its vocabulary still needs."""
    if is_funnel and (freeze is not None or part is not None):
        raise ValueError("funnel charts cannot take freeze= or part=: they are not in time order.")
    if is_funnel and n is None:
        raise ValueError(f"chart={chart!r} requires denominators (n=).")
    if limit_method is not None and chart == "oep":
        raise ValueError("limit_method= is not available for chart='oep'.")
    if limit_method is not None and chart != "oe":
        raise ValueError(f"limit_method= is only valid for chart='oe', got chart={chart!r}.")
    if side not in _WORSE:
        raise ValueError(f"signal_side must be one of {tuple(_WORSE)}, got {side!r}.")
    if method not in ("limits", "fdr"):
        raise ValueError(f"signal_method must be one of ('limits', 'fdr'), got {method!r}.")
    if (side != "both" or method != "limits") and not is_funnel:
        raise ValueError("signal_side= and signal_method= needs funnel contours.")
    if not (len(levels) == 2 and levels[0] > levels[1]):
        raise ValueError(f"levels must be (outer, inner) with outer wider, got {levels!r}.")
    names = ([hover_extra] if isinstance(hover_extra, str) else list(hover_extra or []))
    if set(map(str, names)) & _ENGINE_RESERVED:
        raise ValueError(f"hover_extra names collide with engine columns: {names!r}.")


def _crossings_blanket(r, d) -> np.ndarray:
    parts = d["part"].to_numpy() if "part" in d else np.ones(len(d))
    blanket = np.zeros(len(d), dtype=bool)
    summaries = r.summary.get("parts") or [r.summary]
    if "by_facet" in r.summary:
        return blanket
    y, cl = d["y"].to_numpy(dtype=float), d["cl"].to_numpy(dtype=float)
    useful = np.isfinite(y) & (y != cl) & ~d["excluded"].to_numpy(dtype=bool)
    for i, value in enumerate(dict.fromkeys(parts)):
        if summaries[min(i, len(summaries) - 1)].get("crossings_signal"):
            blanket |= (parts == value) & useful
    return blanket


def _engine_funnel(chart, x, y, n, data, cl, exclude, limit_method, tau_method, signal_side,
                   signal_method, levels, fdr_levels, multiply, point_labels, hover_extra,
                   facets, within_dispersion, tau_fixed, test_min_expected, plot_options):
    measure, adjusted = _FUNNEL_CHARTS[chart]
    if data is None:
        k = len(y)
        units = list(x) if x is not None else list(range(1, k + 1))
        data = pd.DataFrame({"__unit": units, "__y": list(y), "__n": list(n)})
        if point_labels is not None:
            if isinstance(point_labels, str):
                raise ValueError("point_labels= is a column name only with data=; pass a list.")
            if len(point_labels) != k:
                raise ValueError(f"Length of point_labels ({len(point_labels)}) must match y.")
            data["__label"] = list(point_labels)
        if hover_extra is not None:
            if not isinstance(hover_extra, dict):
                raise ValueError("Without data=, hover_extra= must be a dict of sequences.")
            for name, values in hover_extra.items():
                data[str(name)] = list(values)
            hover_extra = [str(name) for name in hover_extra]
        y, n, unit, label = "__y", "__n", "__unit", ("__label" if point_labels is not None else None)
    else:
        unit, label = x, point_labels
        k = len(data)
    if exclude is not None and not isinstance(exclude, str):
        positions = [exclude] if isinstance(exclude, (int, np.integer)) else list(exclude)
        ids = data[unit].tolist() if unit is not None else list(range(1, k + 1))
        exclude = [ids[p - 1] for p in positions if 1 <= p <= len(ids)]
    tau = None
    if tau_fixed is not None:
        tau = ({fv: math.sqrt(v) for fv, v in tau_fixed.items()} if isinstance(tau_fixed, dict)
               else math.sqrt(tau_fixed))
    st = _settings(
        measure=measure, overdispersion=adjusted, tau_method=tau_method or DEFAULT_TAU_METHOD,
        tau=tau, worse=_WORSE[signal_side], signal=signal_method, limits=tuple(levels),
        fdr_levels=tuple(fdr_levels), fdr_min=test_min_expected, multiply=multiply,
        center=cl, facets=facets, limit_method=limit_method or "exact",
    )
    frame, hover = _normalize(data, y, n, unit, label, hover_extra, st.facets, exclude, {})
    r = _funnel(frame, replace(st, hover=tuple(hover)), within_dispersion, False, None,
                {"y": y, "n": n})
    d = r.data
    out = pd.DataFrame({"x": d["unit"]})
    if "label" in d:
        out["label"] = d["label"]
    out["y"] = d["y"]
    out["cl"], out["ucl"], out["lcl"] = d["cl"], d["upper_outlier"], d["lower_outlier"]
    out["ucl_95"], out["lcl_95"] = d["upper_alert"], d["lower_alert"]
    out["sigma_signal"] = d["signal"] == "outlier"
    out["warn_signal"] = d["signal"] == "alert"
    out["runs_signal"] = False
    out["runs_signal_localized"] = False
    out["baseline"] = ~d["excluded"]
    out["excluded"] = d["excluded"]
    if measure == "oe":
        out["min_detectable_oe"] = d["min_detectable"]
    else:
        out["min_detectable"] = d["min_detectable"]
    out["ci_95_lower"], out["ci_95_upper"] = d["ci_lower"], d["ci_upper"]
    if measure == "oe":
        out["observed"], out["expected"] = d["numerator"], d["denominator"]
    out["n"] = d["denominator"]
    out["p_value"], out["q_value"] = d["p_value"], d["q_value"]
    if facets is not None:
        out["facet"] = d[facets]
    for col in hover:
        out[col] = d[col]
    return EngineResult(out, _engine_summary(r, chart, adjusted, measure, signal_side,
                                             signal_method, levels, fdr_levels),
                        chart, "anhoej", public=r, plot_options={
                            k: v for k, v in plot_options.items()
                            if k in ("title", "subtitle", "caption", "xlab", "ylab",
                                     "styles", "x_range", "y_range", "show_legend",
                                     "width", "height", "label_signals")})


def _engine_summary(r, chart, adjusted, measure, side, method, levels, fdr_levels) -> dict:
    def one(s, rows):
        out = {
            "n_obs": int(np.isfinite(rows["y"].to_numpy(dtype=float)).sum()),
            "signals": bool((rows["signal"] == "outlier").any()),
            "n_warn": int((rows["signal"] == "alert").sum()),
            "limit_method": s["limit_method"], "count_model": s["count_model"],
            "p_value_method": s["p_value_method"], "n_tested": s["n_tested"],
            "dispersion_phi": s["phi"], "dispersion_tau": s["tau"],
            "overdispersed": s["tau"] > 0, "runs_disabled": True,
            "signal_side": side, "signal_method": method,
            "levels": tuple(levels), "fdr_levels": tuple(fdr_levels),
            "excluded": [i + 1 for i in np.flatnonzero(rows["excluded"].to_numpy())],
        }
        if adjusted:
            out["dispersion_method"] = "additive"
            out["dispersion_adjusted"] = s["tau"] > 0
        for key in ("dispersion_shape", "within_dispersion_hint", "within_dispersion_hint_source",
                    "n_underpowered", "underpowered", "n_filtered"):
            if s.get(key) is not None:
                out[key] = s[key]
        if s.get("min_detectable_median") is not None:
            name = "min_detectable_oe_median" if measure == "oe" else "min_detectable_ratio_median"
            out[name] = s["min_detectable_median"]
        power = [note for note in s["notes"] if "to detect even a doubling" in note]
        if power:
            out["power_note"] = power[0]
        spread = [note for note in s["notes"] if "Compare with overdispersion=True" in note]
        if spread:
            out["dispersion_note"] = spread[0]
        if chart in ("oe", "oep", "u", "up") or s["within_dispersion"] != 1.0:
            out["within_dispersion"] = s["within_dispersion"]
        return out

    s, d = r.summary, r.data
    if "by_facet" not in s:
        return one(s, d)
    facets = r._meta["facets"]
    by_facet = {name: one(fs, d[d[facets[0]].astype(str) == str(name)])
                for name, fs in s["by_facet"].items()}
    return {"n_obs": sum(f["n_obs"] for f in by_facet.values()),
            "signals": any(f["signals"] for f in by_facet.values()), "by_facet": by_facet,
            "signal_side": side, "signal_method": method, "levels": tuple(levels),
            "fdr_levels": tuple(fdr_levels)}


def engine_paretochart(x, data=None, **_):
    r = paretochart(x, data=data)
    rows = [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()}
            for row in r.data.to_dict("records")]
    return _Plain({"title": "", "subtitle": None, "caption": None, "ylab": "Frequency",
                   "xlab": "", "data": rows}, r.data, {"ylab": "Frequency"})


def engine_bchart(x, target=None, or_ratio=2.0, limit=3.5, **_):
    baseline = int(target) if target is not None and target > 1 else None
    r = bchart(x, target=None if baseline else target, baseline=baseline,
               or_ratio=or_ratio, limit=limit)
    s = r.summary
    rows = [{k: (bool(v) if isinstance(v, np.bool_) else v) for k, v in row.items()}
            for row in r.data.to_dict("records")]
    title = f"Bernoulli CUSUM (p0={s['target']:.3f}, OR={or_ratio})"
    return _Plain({"title": title, "subtitle": None, "caption": None, "ylab": "CUSUM",
                   "xlab": "Case #", "target": s["target"], "or_ratio": or_ratio,
                   "limit": limit, "data": rows}, r.data, s)


@dataclass
class _Plain:
    payload: dict
    data: pd.DataFrame
    summary: dict

    def to_dict(self):
        return self.payload


def experiment_analyze(factors, response, **kwargs):
    d = design(factors=factors, **kwargs)
    return d.fill(response)


DISPATCH = {
    "qic": engine_qic,
    "paretochart": engine_paretochart,
    "bchart": engine_bchart,
    "experiment_design": lambda factors, **kwargs: design(factors=factors, **kwargs),
    "experiment_analyze": experiment_analyze,
}

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

# TypeScript-engine spellings of keyword arguments, mapped to the Python names.
_TS_KEYS = {"clOverride": "cl", "limitMethod": "limit_method", "tauMethod": "tau_method"}
# Inputs only the TypeScript engine reads; Python re-derives them from the grouping column.
_TS_ONLY = ("subgroupN", "sBar", "sigmaHat")


def fixture_paths() -> list[pathlib.Path]:
    """Every shared fixture (spc and experiment), found relative to this file."""
    return sorted(p for sub in ("spc", "experiment") for p in (FIXTURE_DIR / sub).glob("*.json"))


def run_fixture(path: pathlib.Path):
    """(fixture dict, result of calling its function on its inputs)."""
    fix = json.loads(path.read_text())
    inputs = fix["input"].copy()
    if isinstance(inputs.get("data"), dict):
        inputs["data"] = pd.DataFrame(inputs["data"])
    for ts, py in _TS_KEYS.items():
        if ts in inputs:
            inputs[py] = inputs.pop(ts)
    for key in _TS_ONLY:
        inputs.pop(key, None)
    return fix, DISPATCH[fix["function"]](**inputs)


def extract(result, key):
    """Pull a check value from a result object."""
    if key == "signals":
        return bool(result.signals) if hasattr(result, "signals") else None
    data = getattr(result, "data", None)
    if isinstance(data, pd.DataFrame) and key in data.columns:
        return _scalar(data[key].iloc[0])
    payload = getattr(result, "payload", None)
    if payload is not None and key in payload:
        return _scalar(payload[key])
    if hasattr(result, key):
        return _scalar(getattr(result, key))
    summary = getattr(result, "summary", None)
    if summary is not None and key in summary:
        return _scalar(summary[key])
    raise KeyError(f"Key {key!r} not found in result {type(result)}")


def _scalar(v):
    if isinstance(v, (np.floating, float)):
        return float(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer, int)):
        return int(v)
    return v


def funnel_limits(chart, cl, n, tau2=0.0, limit_method="exact", levels=(0.998, 0.95),
                  within_dispersion=1.0) -> dict:
    """The engine's funnel_limits(chart, cl, n): a chart code's contours at any n."""
    from qikit.core.contours import funnel_contours

    measure, adjusted = _FUNNEL_CHARTS[chart]
    family = "binomial" if measure == "proportion" else "poisson"
    n = np.asarray(n, dtype=float)
    if within_dispersion != 1.0:
        n = n / float(within_dispersion)
    lim = funnel_contours(family, cl, n, tau2 if adjusted else 0.0, tuple(levels), limit_method)
    return {"ucl": lim.ucl, "lcl": lim.lcl, "ucl_95": lim.ucl_95, "lcl_95": lim.lcl_95}
