"""
Runs the shared fixtures, which speak the TypeScript engine's vocabulary, on qikit.

fixtures/spc/*.json and fixtures/experiment/*.json are run by both engines: this Python
package and the TypeScript engine of the Excel add-in (excel-addin/packages/engine),
which is frozen and keeps the original engine vocabulary (chart="oe", funnel=True,
sigma_signal, warn_signal, ucl, ...). engine_qic() takes that vocabulary, calls qic() or
funnel()'s pipeline, and returns a result in it, so the fixtures and their snapshots keep
checking the same numbers in both languages.

It covers what the fixtures use, and no more: tests/test_fixture_adapter.py pins the
parts of the vocabulary that are not simply new names. Python tests of the package use
qic() and funnel() directly.
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
from qikit._funnel.inputs import _normalize
from qikit._funnel.pipeline import _funnel
from qikit._funnel.settings import _settings
from qikit.core.dispersion import DEFAULT_TAU_METHOD

# Chart code → (funnel measure, overdispersion).
_FUNNEL_CHARTS = {"oe": ("oe", False), "oep": ("oe", True), "p": ("proportion", False),
                  "pp": ("proportion", True), "u": ("rate", False), "up": ("rate", True)}
_WORSE = {"both": None, "above": "higher", "below": "lower"}
# The engine's fixed signalling settings; the summaries record them.
_LEVELS = (0.998, 0.95)
_FDR_LEVELS = (0.05, 0.10)


@dataclass
class EngineResult:
    """A result in the engine vocabulary: data, summary, signals, and its own to_dict.
    public is the qic() or funnel() result it was read from."""
    data: pd.DataFrame
    summary: dict[str, Any]
    chart_type: str
    method: str
    public: Any = field(repr=False, default=None)

    @property
    def signals(self) -> bool:
        return bool(self.summary.get("signals"))

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
    limit_method=None, tau_method=None, signal_side="both", multiply=1.0, method="anhoej",
    part=None, target=None,
) -> EngineResult:
    """The engine's qic(): a funnel for chart="oe"/"oep" or funnel=True, else a series."""
    chart = chart.lower().strip()
    if chart in ("oe", "oep") or funnel:
        return _engine_funnel(chart, x, y, n, data, cl, exclude, limit_method, tau_method,
                              signal_side, multiply)
    return _engine_series(chart, x, y, n, data, cl, exclude, multiply, method, part, target)


def _engine_series(chart, x, y, n, data, cl, exclude, multiply, method, part, target):
    # The engine's part= gave the point where each part starts; qic's gives where one ends.
    if part is not None and not isinstance(part, str):
        part = [p - 1 for p in ([part] if isinstance(part, (int, np.integer)) else part)]
    r = qic(data, x=x, y=y, n=n, chart=chart, method=method, part=part, exclude=exclude,
            center=cl, target=target, multiply=multiply)
    d = r.data.copy()
    out = pd.DataFrame({"x": d["x"]})
    for col in ("y", "cl", "ucl", "lcl", "ucl_95", "lcl_95"):
        out[col] = d[col]
    out["sigma_signal"] = d["signal"] == "outlier"
    # The engine's runs_signal also marks every useful point when there are too few
    # crossings (a property of the whole series); runs_signal_localized does not.
    out["runs_signal"] = d["runs_signal"] | _crossings_blanket(r, d)
    out["runs_signal_localized"] = d["runs_signal"]
    out["baseline"] = d["baseline"]
    out["excluded"] = d["excluded"]
    for col in ("n", "target", "part"):
        if col in d:
            out[col] = d[col]
    if chart == "mr":  # the engine drops the first point, which has no moving range
        out = out.iloc[1:].reset_index(drop=True)
    # notes and provisional are the front door's words to a reader, not engine numbers,
    # so they stay out of the fixtures the TypeScript engine conforms to.
    s = {k: v for k, v in r.summary.items() if k not in ("notes", "provisional")}
    if "rules_fired" in s:
        s["shift_signal"] = any(name.startswith("shift") for name in s["rules_fired"])
        s["trend_signal"] = any(name.startswith("trend") for name in s["rules_fired"])
    return EngineResult(out, s, chart, method, public=r)


def _crossings_blanket(r, d) -> np.ndarray:
    parts = d["part"].to_numpy() if "part" in d else np.ones(len(d))
    blanket = np.zeros(len(d), dtype=bool)
    summaries = r.summary.get("parts") or [r.summary]
    y, cl = d["y"].to_numpy(dtype=float), d["cl"].to_numpy(dtype=float)
    useful = np.isfinite(y) & (y != cl) & ~d["excluded"].to_numpy(dtype=bool)
    for i, value in enumerate(dict.fromkeys(parts)):
        if summaries[min(i, len(summaries) - 1)].get("crossings_signal"):
            blanket |= (parts == value) & useful
    return blanket


def _engine_funnel(chart, x, y, n, data, cl, exclude, limit_method, tau_method, signal_side,
                   multiply):
    measure, adjusted = _FUNNEL_CHARTS[chart]
    if data is None:
        k = len(y)
        units = list(x) if x is not None else list(range(1, k + 1))
        data = pd.DataFrame({"__unit": units, "__y": list(y), "__n": list(n)})
        y, n, unit = "__y", "__n", "__unit"
    else:
        unit, k = x, len(data)
    # The engine's exclude= is 1-based into the input order; out-of-range is ignored.
    if exclude is not None and not isinstance(exclude, str):
        positions = [exclude] if isinstance(exclude, (int, np.integer)) else list(exclude)
        ids = data[unit].tolist() if unit is not None else list(range(1, k + 1))
        exclude = [ids[p - 1] for p in positions if 1 <= p <= len(ids)]
    # The private pipeline, because limit_method="byar" (one fixture) is not public.
    st = _settings(
        measure=measure, overdispersion=adjusted, tau_method=tau_method or DEFAULT_TAU_METHOD,
        tau=None, worse=_WORSE[signal_side], signal="limits", limits=_LEVELS,
        fdr_levels=_FDR_LEVELS, fdr_min=None, multiply=multiply, center=cl, facets=None,
        limit_method=limit_method or "exact",
    )
    frame, hover = _normalize(data, y, n, unit, None, None, st.facets, exclude, {})
    r = _funnel(frame, replace(st, hover=tuple(hover)), 1.0, False, None, {"y": y, "n": n})
    d = r.data
    out = pd.DataFrame({"x": d["unit"]})
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
    return EngineResult(out, _engine_summary(r, chart, adjusted, measure, signal_side),
                        chart, "anhoej", public=r)


def _engine_summary(r, chart, adjusted, measure, side) -> dict:
    s, rows = r.summary, r.data
    out = {
        "n_obs": int(np.isfinite(rows["y"].to_numpy(dtype=float)).sum()),
        "signals": bool((rows["signal"] == "outlier").any()),
        "n_warn": int((rows["signal"] == "alert").sum()),
        "limit_method": s["limit_method"], "count_model": s["count_model"],
        "p_value_method": s["p_value_method"], "n_tested": s["n_tested"],
        "dispersion_phi": s["phi"], "dispersion_tau": s["tau"],
        "overdispersed": s["tau"] > 0, "runs_disabled": True,
        "signal_side": side, "signal_method": "limits",
        "levels": _LEVELS, "fdr_levels": _FDR_LEVELS,
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
