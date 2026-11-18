"""
charts.py — Plotly figures for SPCResult and FunnelResult.

Both result types are drawn by one renderer from a Drawing: the points, their tiers,
the reference lines and the words around them. plot_spc() and plot_funnel() build it
from their result; everything after that is shared.

Design (Tufte): the series carries the darkest ink and reference lines are light
hairlines; color is reserved for meaning (brick for outliers, amber for runs or
alerts, Making Data Count's blue and orange for improving and concerning special
causes) and every signal also changes the marker, so it survives color-vision
deficiency; lines are labeled at their right-hand end.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .drawing import _FUNNEL_OPTIONS, _SPC_OPTIONS, Drawing, _options
from .layout import _CLUSTERED_CAPTION, _UNDERPOWERED_CAPTION
from .options import COLOR_BY, check_choice
from .render import _render


def plot_spc(result, **given) -> go.Figure:
    """Draw an SPCResult (see SPCResult.plot for the options)."""
    opts = _options(given, _SPC_OPTIONS, "spc")
    d, meta = result.data, result._meta
    facets = meta.get("facets", [])
    if opts["label_signals"] in ("alert", "both"):
        raise ValueError("label_signals='alert' needs a funnel's alert tier; on a qic() chart "
                         "use label_signals='outlier'.")
    frame = pd.DataFrame({
        "key": d["x"].to_numpy(), "pos": d["x"].to_numpy(),
        "display": _display(d["label"] if "label" in d else None, d["x"]),
        "y": d["y"].to_numpy(dtype=float),
        **{c: d[c].to_numpy(dtype=float) for c in ("cl", "ucl", "lcl", "ucl_95", "lcl_95")},
        "outlier": (d["signal"] == "outlier").to_numpy(),
        "alert": np.zeros(len(d), dtype=bool),
        "run": d["runs_signal"].to_numpy(dtype=bool),
        "excluded": d["excluded"].to_numpy(dtype=bool),
        "panel": _panels(d, facets),
    })
    for col in ("notes", "target", "variation", "special_cause", "part"):
        if col in d:
            frame[col] = d[col].to_numpy()
    for col in meta.get("hover", []):
        frame[col] = d[col].to_numpy()
    if opts["runs_highlight"] == "all":
        frame["run"] = frame["run"] | _crossings_blanket(result, frame)
    elif opts["runs_highlight"] == "none":
        frame["run"] = False
    drawing = Drawing(
        frame=frame, funnel=False, title=opts["title"], subtitle=opts["subtitle"],
        caption=opts["caption"],
        xlab=opts["xlab"] if opts["xlab"] is not None else (meta.get("x_name") or "Subgroup"),
        ylab=opts["ylab"] if opts["ylab"] is not None else (meta.get("y_name") or "Value"),
        signals=result.signals,
        percent=meta.get("percent", False) if opts["y_percent"] is None else opts["y_percent"],
        hover=list(meta.get("hover", [])),
    )
    return _render(drawing, opts)


def plot_funnel(result, **given) -> go.Figure:
    """Draw a FunnelResult (see FunnelResult.plot for the options)."""
    opts = _options(given, _FUNNEL_OPTIONS, "funnel")
    d, meta, s = result.data, result._meta, result.summary
    facets = meta.get("facets", [])
    check_choice("color_by", opts["color_by"], COLOR_BY)
    signal = meta.get("signal", "limits")
    fdr_levels = tuple(meta.get("fdr_levels", (0.05, 0.10)))
    by_q = opts["color_by"] == "fdr" or signal == "fdr"
    watch_at = _check_fdr_watch(opts["fdr_watch"], by_q, fdr_levels)
    axis = "effective_denominator" if "effective_denominator" in d else "denominator"
    volume = d[axis].to_numpy(dtype=float)
    # With every denominator equal there is no volume to spread the providers over:
    # draw them by unit, each against its own limits.
    by_volume = np.nanmin(volume) < np.nanmax(volume) if len(volume) else False
    frame = pd.DataFrame({
        "key": d["unit"].to_numpy(),
        "pos": volume if by_volume else _display(d["label"] if "label" in d else None, d["unit"]),
        "display": _display(d["label"] if "label" in d else None, d["unit"]),
        "y": d["y"].to_numpy(dtype=float), "cl": d["cl"].to_numpy(dtype=float),
        "ucl": d["upper_outlier"].to_numpy(dtype=float),
        "lcl": d["lower_outlier"].to_numpy(dtype=float),
        "ucl_95": d["upper_alert"].to_numpy(dtype=float),
        "lcl_95": d["lower_alert"].to_numpy(dtype=float),
        "outlier": (d["signal"] == "outlier").to_numpy(),
        "alert": (d["signal"] == "alert").to_numpy(),
        "run": np.zeros(len(d), dtype=bool),
        "excluded": d["excluded"].to_numpy(dtype=bool),
        "panel": _panels(d, facets),
        **{c: d[c].to_numpy() for c in ("numerator", "denominator", "ci_lower", "ci_upper",
                                        "min_detectable", "p_value", "q_value")},
    })
    for col in meta.get("hover", []):
        frame[col] = d[col].to_numpy()
    recolor = by_q and signal != "fdr"
    q = d["q_value"].to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        if recolor:
            # The tiers signal="fdr" gives (funnel.py), drawn over a signal="limits" result;
            # a provider with no q-value (excluded, below fdr_min_denominator) stays routine.
            frame["outlier"] = q < fdr_levels[0]
            frame["alert"] = (q < fdr_levels[1]) & ~(q < fdr_levels[0])
        if watch_at is not None:
            frame["watch"] = (q < watch_at) & ~(q < fdr_levels[1])
    if "benchmark" in d:
        frame["target"] = d["benchmark"].to_numpy(dtype=float)  # drawn with the target role
        name = "ABC" if "benchmark_group" in d else "Benchmark"
        given_styles = opts["styles"]
        layers = given_styles if isinstance(given_styles, (list, tuple)) else [given_styles]
        opts = {**opts, "styles": [{"target": {"name": name}}, *layers]}
    curve = None
    if by_volume:
        lim = result.limits()
        curve = pd.DataFrame({
            "pos": lim["denominator"].to_numpy(dtype=float),
            "cl": lim["cl"].to_numpy(dtype=float),
            "ucl": lim["upper_outlier"].to_numpy(dtype=float),
            "lcl": lim["lower_outlier"].to_numpy(dtype=float),
            "ucl_95": lim["upper_alert"].to_numpy(dtype=float),
            "lcl_95": lim["lower_alert"].to_numpy(dtype=float),
            "panel": _panels(lim, facets),
        })
    elif opts["x_log"]:
        raise ValueError("x_log=True needs denominators that vary: with every one equal the "
                         "providers are drawn by unit.")
    panels = [s] + list((s.get("by_facet") or {}).values())
    warnings = []
    if any(p.get("dispersion_shape") in ("within", "both")
           and p.get("within_dispersion_source") == "default" for p in panels):
        warnings.append(_CLUSTERED_CAPTION)
    if s.get("underpowered") or any(p.get("underpowered") for p in panels[1:]):
        warnings.append(_UNDERPOWERED_CAPTION)
    measure = meta.get("measure")
    drawing = Drawing(
        frame=frame, funnel=True, title=opts["title"], subtitle=opts["subtitle"],
        caption=opts["caption"],
        xlab=opts["xlab"] if opts["xlab"] is not None else (
            _funnel_xlab(meta, axis) if by_volume else "Provider"),
        ylab=opts["ylab"] if opts["ylab"] is not None else _funnel_ylab(meta),
        curve=curve, levels=tuple(meta.get("limits", (0.998, 0.95))),
        side=meta.get("side", "both"), signal="fdr" if by_q else signal,
        fdr_levels=fdr_levels, fdr_watch=watch_at, n_tested=int(s.get("n_tested", 0)),
        signals=bool(frame["outlier"].any()) if recolor else bool(s.get("n_outlier", 0)),
        percent=(measure == "proportion" and meta.get("multiply", 1.0) == 1.0)
        if opts["y_percent"] is None else opts["y_percent"],
        warnings=warnings, hover=list(meta.get("hover", [])), measure=measure,
    )
    opts = {**opts, "show_95": True, "runs_highlight": "none", "connect": False,
            "x_order": None, "x_format": None, "x_angle": None, "y_neg": True,
            "y_expand": None, "show_grid": False, "flip": False, "by_volume": by_volume}
    return _render(drawing, opts)


def _check_fdr_watch(value, by_q: bool, fdr_levels: tuple) -> float | None:
    """fdr_watch=: a q-value cut looser than the alert tier, on a chart colored by q."""
    if value is None:
        return None
    if not by_q:
        raise ValueError("fdr_watch= draws a tier of q-values; color the points by them with "
                         "color_by='fdr' (or fit with signal='fdr').")
    ok = (isinstance(value, (int, float)) and not isinstance(value, bool)
          and fdr_levels[1] < value < 1.0)
    if not ok:
        raise ValueError(f"fdr_watch must be a number above the alert level {fdr_levels[1]:g} "
                         f"and below 1, e.g. 0.20. Got {value!r}.")
    return float(value)


def _display(labels, keys) -> list[str]:
    keys = list(keys)
    if labels is None:
        return [str(k) for k in keys]
    return [str(lab) if isinstance(lab, str) and lab else str(k) for lab, k in zip(labels, keys)]


def _panels(d: pd.DataFrame, facets: list[str]):
    if not facets:
        return np.full(len(d), None, dtype=object)
    return np.array([" / ".join(str(v) for v in row)
                     for row in d[facets].itertuples(index=False, name=None)], dtype=object)


def _crossings_blanket(result, frame) -> np.ndarray:
    """
    runs_highlight="all": every useful point of a part (in each facet) whose crossings
    rule fired, the whole-series pattern the default leaves to the summary.
    """
    s = result.summary
    y, cl = frame["y"].to_numpy(dtype=float), frame["cl"].to_numpy(dtype=float)
    useful = np.isfinite(y) & (y != cl) & ~frame["excluded"].to_numpy(dtype=bool)
    parts = frame["part"].to_numpy() if "part" in frame else np.ones(len(frame))
    panels = frame["panel"].to_numpy()
    out = np.zeros(len(frame), dtype=bool)
    for panel in dict.fromkeys(panels):
        summary = s["by_facet"][panel] if panel is not None else s
        rows = panels == panel
        summaries = summary.get("parts") or [summary]
        for i, value in enumerate(dict.fromkeys(parts[rows])):
            if summaries[min(i, len(summaries) - 1)].get("crossings_signal"):
                out |= rows & (parts == value) & useful
    return out


def _funnel_xlab(meta: dict, axis: str) -> str:
    base = meta.get("n_name") or {"oe": "Expected", "proportion": "Cases",
                                  "rate": "Exposure", "mean": "Cases"}.get(str(meta.get("measure")), "Volume")
    if axis == "effective_denominator":
        return f"Effective {base} ({base} / {meta.get('phi_column')})"
    return base


def _funnel_ylab(meta: dict) -> str:
    measure, y, n = meta.get("measure"), meta.get("y_name"), meta.get("n_name")
    if measure == "oe":
        return "Observed / expected"
    if measure == "mean":
        return f"Mean {y}" if y else "Mean"
    if not (y and n):
        return "Proportion" if measure == "proportion" else "Rate"
    if measure == "proportion":
        return f"{y} / {n}"
    m = meta.get("multiply", 1.0)
    per = f"{m:g} " if m != 1.0 else ""
    return f"{y} per {per}{n}"
