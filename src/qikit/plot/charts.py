"""
charts.py — Plotly figures for SPCResult and FunnelResult (and Pareto, Bernoulli CUSUM).

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

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..core.pvalues import signal_thresholds
from .options import (
    COLOR_BY, LABEL_SIGNALS, RUNS_HIGHLIGHT, check_choice, validate_range, validate_styles,
)
from .theme import (
    AXIS, CL, CONTOUR, CONCERNING, GRID, IMPROVING, LIMIT, NEUTRAL, NORMAL, RUNS, SIGMA,
    TARGET, TEXT, TEXT_FAINT, TEXT_MUTED, WARN, WATCH, apply_tufte_theme,
)


@dataclass
class Drawing:
    """What one figure draws, whichever result it came from."""
    frame: pd.DataFrame          # pos, y, cl, ucl, lcl, ucl_95, lcl_95, outlier, alert,
                                 # run, excluded, key, display, panel, and hover fields
    funnel: bool
    title: str = ""
    subtitle: str | None = None
    caption: str | None = None
    xlab: str = ""
    ylab: str = ""
    curve: pd.DataFrame | None = None   # funnel contours: pos, cl, ucl, lcl, ucl_95, lcl_95, panel
    levels: tuple = (0.998, 0.95)
    side: str = "both"
    signal: str = "limits"
    fdr_levels: tuple = (0.05, 0.10)
    fdr_watch: float | None = None
    n_tested: int = 0
    signals: bool = False
    percent: bool = False
    warnings: list[str] = field(default_factory=list)   # captions that are never dropped
    hover: list[str] = field(default_factory=list)       # extra tooltip columns
    measure: str | None = None


_SPC_OPTIONS = dict(
    title="", subtitle=None, caption=None, xlab=None, ylab=None, show_95=False,
    show_labels=True, show_grid=False, show_x_labels=True, label_signals=None,
    runs_highlight="localized", styles=None, x_range=None, y_range=None, x_order=None,
    x_format=None, x_angle=None, y_percent=None, y_neg=True, y_expand=None, decimals=None,
    point_size=1.5, connect=None, show_legend=False, flip=False, width=None, height=None,
    nrow=None, ncol=None, scales="fixed",
)
_FUNNEL_OPTIONS = dict(
    title="", subtitle=None, caption=None, xlab=None, ylab=None, label_signals=None,
    styles=None, x_log=False, x_range=None, y_range=None, show_legend=True,
    show_x_labels=True, show_labels=False, width=None, height=None, nrow=None, ncol=None,
    scales="fixed", decimals=None, point_size=1.5, y_percent=None, color_by="signal",
    fdr_watch=None,
)


def _options(given: dict, defaults: dict, kind: str) -> dict:
    unknown = sorted(set(given) - set(defaults))
    if unknown:
        hint = ""
        if kind == "funnel" and set(unknown) & {"x_order", "runs_highlight", "connect"}:
            hint = " A funnel is drawn against volume; those options apply to qic() charts."
        raise TypeError(f"plot() got unexpected keyword argument(s) {unknown}. Valid names: "
                        f"{sorted(defaults)}.{hint}")
    opts = {**defaults, **given}
    check_choice("label_signals", opts["label_signals"], LABEL_SIGNALS)
    if "runs_highlight" in opts:
        check_choice("runs_highlight", opts["runs_highlight"], RUNS_HIGHLIGHT)
    check_choice("scales", opts["scales"], ("fixed", "free"))
    validate_styles(opts["styles"])
    opts["x_range"] = validate_range("x_range", opts["x_range"], numeric=kind == "funnel")
    opts["y_range"] = validate_range("y_range", opts["y_range"], numeric=True)
    return opts


# ---------------------------------------------------------------------------
# From results to drawings
# ---------------------------------------------------------------------------

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
                                  "rate": "Exposure"}.get(str(meta.get("measure")), "Volume")
    if axis == "effective_denominator":
        return f"Effective {base} ({base} / {meta.get('phi_column')})"
    return base


def _funnel_ylab(meta: dict) -> str:
    measure, y, n = meta.get("measure"), meta.get("y_name"), meta.get("n_name")
    if measure == "oe":
        return "Observed / expected"
    if not (y and n):
        return "Proportion" if measure == "proportion" else "Rate"
    if measure == "proportion":
        return f"{y} / {n}"
    m = meta.get("multiply", 1.0)
    per = f"{m:g} " if m != 1.0 else ""
    return f"{y} per {per}{n}"


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _pct(coverage: float) -> str:
    """0.998 → "99.8%", 0.95 → "95%"."""
    return f"{coverage * 100:g}%"


def _resolve_styles(styles: Any, drawing: Drawing) -> dict[str, dict]:
    """
    Every role with its defaults, overlaid with the caller's attributes. A funnel's
    contours are what a reader judges each provider against, often on a projector, so
    they are drawn at 3.5:1 contrast, the inner one dashed, and its points at 0.85
    opacity so overlapping providers stay visible.
    """
    funnel = drawing.funnel
    if funnel:
        o, i = _pct(drawing.levels[0]), _pct(drawing.levels[1])
        outer, inner = (f"{o}+", f"{o}-"), (f"{i}+", f"{i}-")
    else:
        outer, inner = ("UCL", "LCL"), ("2σ+", "2σ-")
    line = {"width": 1, "dash": None, "visible": True}
    limit = {**line, "color": CONTOUR, "width": 1.5} if funnel else {**line, "color": LIMIT}
    inner_line = ({**line, "color": CONTOUR, "dash": "dash"} if funnel
                  else {**line, "color": WARN, "dash": "dot"})
    base: dict[str, dict] = {
        "data": {"color": NORMAL, "width": 1, "name": "data", "opacity": 0.85 if funnel else 1.0},
        "outlier": {"color": SIGMA, "name": None},
        "alert": {"color": RUNS, "name": None},
        "watch": {"color": WATCH, "name": None},
        "runs": {"color": RUNS, "name": None},
        "improving": {"color": IMPROVING, "name": None},
        "concerning": {"color": CONCERNING, "name": None},
        "neutral": {"color": NEUTRAL, "name": None},
        "cl": {**line, "color": CONTOUR if funnel else CL, "name": "CL"},
        "ucl": {**limit, "name": outer[0]},
        "lcl": {**limit, "name": outer[1]},
        "ucl_95": {**inner_line, "name": inner[0]},
        "lcl_95": {**inner_line, "name": inner[1]},
        "target": {**line, "color": TARGET, "dash": "dot", "name": "Target"},
        "end_labels": {"color": TEXT_MUTED, "size": 10},
        "font": {"family": None, "size": None, "color": None},
    }
    for role, attrs in validate_styles(styles).items():
        base[role] = {**base[role], **attrs}
    return base


def _line(style: dict) -> dict:
    out = {"color": style["color"], "width": style["width"]}
    if style.get("dash") is not None:
        out["dash"] = style["dash"]
    return out


# Every signal changes the marker as well as the color; the watch tier is drawn open.
_SYMBOLS = {"runs": "diamond", "alert": "diamond", "watch": "diamond-open"}


def _point_roles(frame: pd.DataFrame) -> list[str | None]:
    """
    The role that colors each point: an outlier first, then a Making Data Count reading
    (improving, concerning, neutral) where there is one, then an alert, a funnel's watch
    tier, or a run.
    """
    variation = frame["variation"].to_numpy() if "variation" in frame else None
    watch = frame["watch"].to_numpy(dtype=bool) if "watch" in frame else np.zeros(len(frame), bool)
    roles: list[str | None] = []
    for i, (o, a, r) in enumerate(zip(frame["outlier"], frame["alert"], frame["run"])):
        v = variation[i] if variation is not None else None
        if v in ("improving", "concerning", "neutral"):
            roles.append(v)
        elif o:
            roles.append("outlier")
        elif a:
            roles.append("alert")
        elif watch[i]:
            roles.append("watch")
        elif r:
            roles.append("runs")
        else:
            roles.append(None)
    return roles


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render(drawing: Drawing, opts: dict) -> go.Figure:
    frame = drawing.frame
    panels = list(dict.fromkeys(frame["panel"]))
    faceted = panels != [None]
    if faceted:
        n = len(panels)
        ncol, nrow = opts["ncol"], opts["nrow"]
        if ncol is None and nrow is None:
            ncol = min(3, n)
        if ncol is None:
            ncol = math.ceil(n / nrow)
        nrow = math.ceil(n / ncol) if nrow is None else nrow
        fig = make_subplots(rows=nrow, cols=ncol, shared_xaxes=True,
                            shared_yaxes=opts["scales"] == "fixed", horizontal_spacing=0.06,
                            vertical_spacing=0.10, subplot_titles=[str(p) for p in panels])
        for ann in fig.layout.annotations:
            ann.font = dict(size=11, color=TEXT_MUTED)
        cells = [(i // ncol + 1, i % ncol + 1) for i in range(n)]
    else:
        fig, cells = go.Figure(), [(None, None)]

    traced = []
    for idx, (panel, (row, col)) in enumerate(zip(panels, cells)):
        sub = frame[frame["panel"] == panel] if faceted else frame
        curve = None
        if drawing.curve is not None:
            curve = drawing.curve[drawing.curve["panel"] == panel] if faceted else drawing.curve
        legend = (idx == 0) if opts["show_legend"] else None
        traced.append(_add_panel(fig, drawing, sub, curve, opts, row, col, legend))

    if opts["show_legend"]:
        _add_legend_entries(fig, drawing, opts)
    x_log = bool(opts.get("x_log"))
    x_bounds, y_bounds = _fit_ranges(
        traced, opts["x_range"], opts["y_range"], x_log, opts["y_neg"], opts["y_expand"],
        shared_y=opts["scales"] == "fixed", fit_y=opts.get("by_volume", False),
    )
    _configure_layout(fig, drawing, opts, x_range_set=x_bounds is not None,
                      fit_y=y_bounds is not None)
    _apply_ranges(fig, traced, x_bounds, y_bounds, x_log, opts["flip"])
    font = {k: v for k, v in (validate_styles(opts["styles"]).get("font") or {}).items()
            if v is not None}
    if font:
        fig.update_layout(font=font)
    if faceted:
        for axis_name in fig.layout:
            if axis_name.startswith(("xaxis", "yaxis")) and fig.layout[axis_name].showticklabels is False:
                fig.layout[axis_name].ticks = ""
    return fig


def _add_panel(fig, drawing: Drawing, df: pd.DataFrame, curve, opts, row, col, legend):
    """Points, reference lines, end labels, part lines, notes and signal labels for one panel."""
    st = _resolve_styles(opts["styles"], drawing)
    funnel = drawing.funnel
    where = {"row": row, "col": col} if row is not None else {}
    x_log = bool(opts.get("x_log"))
    x = df["pos"].tolist()
    y = df["y"].to_numpy(dtype=float)
    cl, ucl, lcl = (df[c].to_numpy(dtype=float) for c in ("cl", "ucl", "lcl"))
    display = df["display"].tolist()

    def ax(v):
        """An x position as an annotation takes it: log10 of the value on a log axis."""
        if not x_log:
            return v
        return math.log10(v) if v > 0 else None

    if curve is not None:
        ref_x = curve["pos"].tolist()
        ref_cl, ref_ucl, ref_lcl = (curve[c].to_numpy(dtype=float) for c in ("cl", "ucl", "lcl"))
        ref_95 = (curve["ucl_95"].to_numpy(dtype=float), curve["lcl_95"].to_numpy(dtype=float))
    else:
        ref_x, ref_cl, ref_ucl, ref_lcl = x, cl, ucl, lcl
        ref_95 = (df["ucl_95"].to_numpy(dtype=float), df["lcl_95"].to_numpy(dtype=float))

    roles = _point_roles(df)
    colors = [st[r]["color"] if r else st["data"]["color"] for r in roles]
    symbols = [_SYMBOLS.get(r or "", "circle") for r in roles]
    base = opts["point_size"] * 6
    sizes = [base * 1.3 if r and r != "watch" else base for r in roles]
    excluded = df["excluded"].to_numpy(dtype=bool)
    opacities = [0.35 if ex else st["data"]["opacity"] for ex in excluded]

    def legend_kw(group=None, entry=True):
        if legend is None:
            return {}
        out: dict[str, Any] = {"showlegend": bool(legend and entry)}
        if group is not None:
            out["legendgroup"] = group
        return out

    if opts.get("connect") is not None:
        mode = "lines+markers" if opts["connect"] else "markers"
    elif funnel:
        mode = "markers"
    else:
        categorical = all(isinstance(v, str) for v in x)
        sequential = any(any(p in str(v).lower() for p in ("-", "/", "week", "wk", "case", "obs", "pt"))
                         for v in x)
        mode = "markers" if categorical and not sequential else "lines+markers"

    customdata, hovertemplate = _hover(drawing, df, excluded)
    text = df["notes"].tolist() if "notes" in df else None
    if text:
        hovertemplate = hovertemplate.replace("<extra>", "<br>%{text}<extra>", 1)
    fig.add_trace(go.Scatter(
        x=x, y=y, mode=mode,
        line=dict(color=st["data"]["color"], width=st["data"]["width"]),
        marker=dict(color=colors, symbol=symbols, size=sizes, opacity=opacities,
                    # An open marker is all outline: give the watch tier's a stroke.
                    line=dict(width=[1.5 if r == "watch" else 0 for r in roles], color=colors)),
        name=st["data"]["name"], text=text, customdata=customdata,
        hovertemplate=hovertemplate, connectgaps=False, cliponaxis=False, zorder=2,
        **legend_kw("data", entry=False),
    ), **where)

    if "target" in df:
        target = df["target"].to_numpy(dtype=float)
        if not np.all(np.isnan(target)) and st["target"]["visible"]:
            fig.add_trace(go.Scatter(x=x, y=target, mode="lines", line=_line(st["target"]),
                                     name=st["target"]["name"], hoverinfo="skip", zorder=1,
                                     **legend_kw()), **where)

    if st["cl"]["visible"]:
        fig.add_trace(go.Scatter(x=ref_x, y=ref_cl, mode="lines", line=_line(st["cl"]),
                                 name=st["cl"]["name"], hoverinfo="skip", zorder=1,
                                 **(legend_kw("cl", entry=False) if funnel else legend_kw())),
                      **where)
    drawn: list[tuple[np.ndarray, bool]] = []
    for arr, role in ((ref_ucl, "ucl"), (ref_lcl, "lcl")):
        if not np.all(np.isnan(arr)) and st[role]["visible"]:
            fig.add_trace(go.Scatter(
                x=ref_x, y=arr, mode="lines", line=_line(st[role]), name=st[role]["name"],
                hoverinfo="skip", zorder=1,
                **legend_kw("limits", entry=not funnel and (role == "ucl" or not st["ucl"]["visible"])),
            ), **where)
            drawn.append((arr, role == "ucl"))
    if opts["show_95"] and not np.all(np.isnan(ucl)):
        for arr, role in ((ref_95[0], "ucl_95"), (ref_95[1], "lcl_95")):
            if not st[role]["visible"]:
                continue
            fig.add_trace(go.Scatter(
                x=ref_x, y=arr, mode="lines", line=_line(st[role]), name=st[role]["name"],
                hoverinfo="skip", zorder=1,
                **legend_kw("limits_95", entry=not funnel and (role == "ucl_95" or not st["ucl_95"]["visible"])),
            ), **where)
            drawn.append((np.asarray(arr, dtype=float), role == "ucl_95"))

    if opts["show_labels"] and len(x):
        scale = 100.0 if drawing.percent else 1.0
        places = (opts["decimals"] if opts["decimals"] is not None
                  else _label_decimals(ref_cl * scale, ref_ucl * scale, ref_lcl * scale))
        fmt = f"{{:.{places}{'%' if drawing.percent else 'f'}}}"
        for arr, role in ((ref_cl, "cl"), (ref_ucl, "ucl"), (ref_lcl, "lcl")):
            valid = np.flatnonzero(~np.isnan(arr))
            if not st[role]["visible"] or not len(valid):
                continue
            last = int(valid[-1])
            fig.add_annotation(
                x=ax(ref_x[last]), y=float(arr[last]),
                text=f"{st[role]['name']}={fmt.format(float(arr[last]))}",
                xshift=12, showarrow=False, xanchor="left",
                font=dict(size=st["end_labels"]["size"], color=st["end_labels"]["color"]),
                **where,
            )

    if "part" in df:
        parts = df["part"].tolist()
        for i in range(1, len(parts)):
            if parts[i] != parts[i - 1]:
                fig.add_vline(x=x[i], line=dict(color=LIMIT, width=1), **where)
                # A separate annotation: add_vline's own label averages x, which fails
                # on a categorical axis (text dates read from a CSV).
                if not isinstance(parts[i], (int, np.integer)):
                    fig.add_annotation(x=x[i], y=1, yref="y domain", yanchor="bottom",
                                       text=str(parts[i]), showarrow=False,
                                       font=dict(size=9, color=TEXT_FAINT), **where)

    notes = [str(v) for v in df["notes"]] if "notes" in df else [""] * len(x)
    labeled: set[int] = set()
    if opts["label_signals"] is not None and len(x):
        flagged = np.zeros(len(x), dtype=bool)
        if opts["label_signals"] in ("outlier", "both"):
            flagged |= df["outlier"].to_numpy(dtype=bool)
        if opts["label_signals"] in ("alert", "both"):
            flagged |= df["alert"].to_numpy(dtype=bool)
        idx = [int(i) for i in np.flatnonzero(flagged) if np.isfinite(y[i])]
        if opts.get("by_volume"):
            coord = np.array([ax(v) if ax(v) is not None else np.nan for v in x], dtype=float)
            finite = coord[np.isfinite(coord)]
            lo, hi = (float(finite.min()), float(finite.max())) if len(finite) else (0.0, 0.0)
            positions = [(coord[i] - lo) / (hi - lo) * len(x) for i in idx] if hi > lo else idx
        elif isinstance(opts.get("x_order"), list):
            order = {v: k for k, v in enumerate(opts["x_order"])}
            positions = [order.get(x[i], i) for i in idx]
        else:
            positions = idx
        above = [bool(np.isnan(cl[i]) or y[i] >= cl[i]) for i in idx]
        offsets = _signal_label_offsets(positions, above, max(1, math.ceil(len(x) / 15)))
        for i, (dx, dy) in zip(idx, offsets):
            note = notes[i].strip()
            role = roles[i] or "outlier"
            fig.add_annotation(
                x=ax(x[i]), y=y[i], text=f"{display[i]} — {note}" if note else display[i],
                showarrow=True, arrowhead=0, arrowcolor=AXIS, arrowwidth=1,
                font=dict(size=10, color=st[role]["color"]), ax=dx, ay=dy, **where,
            )
            labeled.add(i)
    for i, note in enumerate(notes):
        if i not in labeled and note.strip():
            fig.add_annotation(x=ax(x[i]), y=y[i], text=note, showarrow=True, arrowhead=1,
                               arrowcolor=AXIS, arrowwidth=1, font=dict(size=9, color=TEXT_MUTED),
                               ax=0, ay=-25, **where)

    keys = df["key"].tolist()
    if not funnel and display != [str(k) for k in keys] and all(isinstance(v, str) for v in keys):
        fig.update_xaxes(tickvals=x, ticktext=display, **where)
    return {"row": row, "col": col, "x": x, "y": y, "ref_x": ref_x,
            "cl": np.asarray(ref_cl, dtype=float), "limits": drawn}


def _hover(drawing: Drawing, df: pd.DataFrame, excluded: np.ndarray):
    """(customdata, hovertemplate): the point's name, value, and what a reader needs next."""
    rows = [[f"{name}{' (excluded)' if ex else ''}"] for name, ex in zip(df["display"], excluded)]
    template = "%{customdata[0]}: %{y}"
    if drawing.funnel:
        unit = {"oe": ("observed", "expected"), "proportion": ("events", "cases"),
                "rate": ("events", "exposure")}.get(str(drawing.measure), ("numerator", "denominator"))
        smallest = "Smallest detectable O/E" if drawing.measure == "oe" else "Smallest detectable"
        tail = {"above": "above", "below": "below", "both": "two-sided"}[drawing.side]
        for r, num, den, lo, hi, det, p, q in zip(
                rows, df["numerator"], df["denominator"], df["ci_lower"], df["ci_upper"],
                df["min_detectable"], df["p_value"], df["q_value"]):
            r += [f"{_fmt(num, 0 if float(num).is_integer() else 1)} {unit[0]} / "
                  f"{_fmt(den, 1)} {unit[1]}",
                  f"{_fmt(lo, 3)}–{_fmt(hi, 3)}", _fmt(det, 3),
                  f"{_fmt_p(p)} ({tail}), q = {_fmt_p(q)}"]
        template += ("<br>%{customdata[1]}<br>95% CI: %{customdata[2]}"
                     f"<br>{smallest}: %{{customdata[3]}}<br>p = %{{customdata[4]}}")
    for name in drawing.hover:
        k = len(rows[0]) if rows else 0
        for r, v in zip(rows, df[name]):
            r.append(_fmt_hover(v))
        template += f"<br>{name}: %{{customdata[{k}]}}"
    if "special_cause" in df:
        k = len(rows[0]) if rows else 0
        for r, v in zip(rows, df["special_cause"]):
            r.append(str(v))
        template += f"<br>%{{customdata[{k}]}}"
    return rows, template + "<extra></extra>"


def _fmt(v, places: int) -> str:
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{float(v):.{places}f}"


def _fmt_p(v) -> str:
    if v is None or np.isnan(v):
        return "n/a"
    return "<0.0001" if v < 1e-4 else f"{v:.2g}"


def _fmt_hover(v) -> str:
    if v is None or (isinstance(v, (float, np.floating)) and np.isnan(v)):
        return "n/a"
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v))
    if isinstance(v, (float, np.floating)):
        return str(int(v)) if float(v).is_integer() else f"{float(v):g}"
    return str(v)


def _label_decimals(*arrays: np.ndarray) -> int:
    """Decimal places for the end labels: about three significant figures of the spread."""
    vals = np.concatenate([np.asarray(a, dtype=float).ravel() for a in arrays if a is not None])
    vals = vals[np.isfinite(vals)]
    if not len(vals):
        return 1
    spread = float(np.max(vals) - np.min(vals)) or abs(float(vals[0])) or 1.0
    return int(np.clip(2 - math.floor(math.log10(spread)), 0, 4))


_LABEL_LEVELS = (22, 38, 54)


def _signal_label_offsets(positions, above, min_gap):
    """
    Arrow offsets (ax, ay) for signal labels: up above the line and down below it, and
    along each side a label close to the previous one steps to the next of three
    levels, so a cluster of flagged neighbors stays legible.
    """
    out = [(0, 0)] * len(positions)
    for side in (True, False):
        idx = sorted((i for i in range(len(positions)) if bool(above[i]) == side),
                     key=lambda i: positions[i])
        level, prev = 0, None
        for i in idx:
            close = prev is not None and positions[i] - prev <= min_gap
            level = (level + 1) % len(_LABEL_LEVELS) if close else 0
            out[i] = (0 if level == 0 else (12 if level % 2 else -12),
                      -_LABEL_LEVELS[level] if side else _LABEL_LEVELS[level])
            prev = positions[i]
    return out


# ---------------------------------------------------------------------------
# Axes, legend, captions
# ---------------------------------------------------------------------------

_X_PAD, _Y_PAD = 0.02, 0.05


def _x_coords(values):
    vals = list(values)
    if all(v is None or (isinstance(v, (int, float, np.number)) and not isinstance(v, bool))
           for v in vals):
        return np.array([np.nan if v is None else float(v) for v in vals]), False
    return pd.to_datetime(pd.Series(vals, dtype=object), errors="coerce").to_numpy(), True


def _within(coords, lo, hi):
    c = np.asarray(coords)
    mask = ~pd.isna(c)
    if lo is not None:
        mask &= c >= lo
    if hi is not None:
        mask &= c <= hi
    return np.asarray(mask, dtype=bool)


def _fit_ranges(panels, x_range, y_range, x_log, y_neg, y_expand, shared_y, fit_y=False):
    """
    Axis ranges for x_range= / y_range=. The y axis is fitted to the points inside the x
    range, the center line there, and each drawn limit's value nearest the center line,
    which keeps a funnel's narrow end in view while its low-volume flare no longer sets
    the scale. An end the caller gave is used as given.
    """
    if x_range is None and y_range is None and not fit_y:
        return None, None
    x_bounds = None
    if x_range is not None:
        if all(isinstance(v, str) for v in panels[0]["x"]):
            raise ValueError("x_range= needs a numeric or date x axis; this one is categorical. "
                             "Choose categories with x_order= instead.")
        is_date = _x_coords(panels[0]["x"])[1]
        conv = pd.Timestamp if is_date else float
        lo, hi = (None if v is None else conv(v) for v in x_range)
        if x_log and any(v is not None and v <= 0 for v in (lo, hi)):
            raise ValueError("x_range on a log axis needs positive ends.")
        if lo is None or hi is None:
            data = np.concatenate([np.asarray(_x_coords(p[key])[0]) for p in panels
                                   for key in ("x", "ref_x")])
            data = data[~pd.isna(data)]
            if x_log and not is_date:
                data = data[data > 0]
            if len(data):
                d_lo, d_hi = data.min(), data.max()
                if is_date:
                    pad = (d_hi - d_lo) * _X_PAD
                    lo = pd.Timestamp(d_lo - pad) if lo is None else lo
                    hi = pd.Timestamp(d_hi + pad) if hi is None else hi
                elif x_log:
                    span = math.log10(d_hi) - math.log10(d_lo)
                    lo = 10 ** (math.log10(d_lo) - span * _X_PAD) if lo is None else lo
                    hi = 10 ** (math.log10(d_hi) + span * _X_PAD) if hi is None else hi
                else:
                    pad = (d_hi - d_lo) * _X_PAD
                    lo = float(d_lo - pad) if lo is None else lo
                    hi = float(d_hi + pad) if hi is None else hi
        x_bounds = (lo, hi)
    given = (None, None) if y_range is None else tuple(y_range)
    if x_range is None and None not in given:
        return x_bounds, [given] * len(panels)
    lo_x, hi_x = x_bounds if x_bounds is not None else (None, None)
    fits = []
    for p in panels:
        inside = _within(_x_coords(p["x"])[0], lo_x, hi_x)
        ref_inside = _within(_x_coords(p["ref_x"])[0], lo_x, hi_x)
        y = np.asarray(p["y"], dtype=float)
        vals = list(y[inside & np.isfinite(y)])
        vals += list(p["cl"][ref_inside & np.isfinite(p["cl"])])
        for arr, upper in p["limits"]:
            a = arr[ref_inside & np.isfinite(arr)]
            if len(a):
                vals.append(float(a.min() if upper else a.max()))
        fits.append((min(vals), max(vals)) if vals else None)
    if shared_y:
        known = [f for f in fits if f is not None]
        union = (min(f[0] for f in known), max(f[1] for f in known)) if known else None
        fits = [union] * len(fits)
    out = []
    for f in fits:
        if f is None:
            out.append(given)
            continue
        lo, hi = f
        pad = (hi - lo) * _Y_PAD or abs(hi) * _Y_PAD or 1.0
        lo, hi = lo - pad, hi + pad
        if not y_neg:
            lo = max(lo, 0.0)
        if y_expand is not None:
            lo, hi = min(lo, y_expand), max(hi, y_expand)
        out.append((given[0] if given[0] is not None else lo,
                    given[1] if given[1] is not None else hi))
    return x_bounds, out


def _apply_ranges(fig, panels, x_bounds, y_bounds, x_log, flip):
    if x_bounds is not None:
        lo, hi = x_bounds
        if x_log:
            lo, hi = math.log10(lo), math.log10(hi)
        fig.update_xaxes(range=[hi, lo] if flip else [lo, hi])
    if y_bounds is None:
        return
    for p, bounds in zip(panels, y_bounds):
        if bounds is None or None in bounds:
            continue
        where = {"row": p["row"], "col": p["col"]} if p["row"] is not None else {}
        fig.update_yaxes(range=list(bounds), **where)


def _add_legend_entries(fig, drawing: Drawing, opts) -> None:
    """
    Legend-only markers for the series and each signal color the figure draws (the
    colors live on one data trace), and on a funnel one entry per contour pair.
    """
    st = _resolve_styles(opts["styles"], drawing)
    given = validate_styles(opts["styles"])
    f = drawing.frame
    drawn = np.isfinite(f["y"].to_numpy(dtype=float))
    roles = np.array(_point_roles(f), dtype=object)
    worse = "Worse than expected: " if drawing.side != "both" else ""
    if not drawing.funnel:
        names = {"outlier": "Beyond UCL/LCL", "runs": "Run signal"}
    elif drawing.signal == "fdr":
        q0, q1 = drawing.fdr_levels
        names = {"outlier": f"{worse}outlier (q < {q0:g})", "alert": f"{worse}alert (q < {q1:g})",
                 "watch": f"{worse}watch (q < {drawing.fdr_watch:g})" if drawing.fdr_watch else ""}
    else:
        names = {"outlier": f"{worse}outlier (beyond {_pct(drawing.levels[0])})",
                 "alert": f"{worse}alert (beyond {_pct(drawing.levels[1])})"}
    names.update({"improving": "Improving", "concerning": "Concerning",
                  "neutral": "Special cause"})
    size = opts["point_size"] * 6
    series = st["data"]["name"]
    if drawing.funnel and not (given.get("data") or {}).get("name"):
        series = "Provider"
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                             marker=dict(color=st["data"]["color"], symbol="circle", size=size),
                             name=series, legendgroup="data", showlegend=True,
                             hoverinfo="skip", legendrank=1))
    for role in ("outlier", "alert", "watch", "runs", "improving", "concerning", "neutral"):
        if not np.any((roles == role) & drawn):
            continue
        name = st[role]["name"] or names[role]
        watch = role == "watch"
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(color=st[role]["color"], size=size if watch else size * 1.3,
                        symbol=_SYMBOLS.get(role, "circle"),
                        line=dict(width=1.5 if watch else 0, color=st[role]["color"])),
            name=name[0].upper() + name[1:], showlegend=True, hoverinfo="skip",
        ))
    if not drawing.funnel:
        return
    if st["cl"]["visible"]:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", line=_line(st["cl"]),
                                 name=(given.get("cl") or {}).get("name") or "Center line",
                                 legendgroup="cl", showlegend=True, hoverinfo="skip"))
    for group, upper, lower, coverage in (("limits", "ucl", "lcl", drawing.levels[0]),
                                          ("limits_95", "ucl_95", "lcl_95", drawing.levels[1])):
        role = upper if st[upper]["visible"] else lower
        if not st[role]["visible"]:
            continue
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="lines", line=_line(st[role]),
            name=(given.get(upper) or {}).get("name") or f"{_pct(coverage)} limits",
            legendgroup=group, showlegend=True, hoverinfo="skip",
        ))


# Captions that travel with the image: these charts get screenshotted into credentialing
# packets, and no summary key travels with a screenshot.
_UNDERPOWERED_CAPTION = (
    "Most points lack the volume to detect a doubling of risk; absence of a signal "
    "is not evidence of acceptable performance."
)
_CLUSTERED_CAPTION = (
    "Warning: counts look clustered within providers (e.g. patient-days), so these "
    "limits are too narrow; set within_dispersion."
)


def _signal_caption(drawing: Drawing) -> str | None:
    """The rule that colored a funnel's points: the test and its levels, or the FDR rule."""
    if not drawing.funnel:
        return None
    tail = "two-sided" if drawing.side == "both" else f"one-sided, {drawing.side} the center line"
    lv = drawing.levels
    if drawing.signal == "limits":
        outer, inner = signal_thresholds(drawing.side, lv)
        return (f"Outlier: beyond the {_pct(lv[0])} limit (exact test, {tail}, p < {outer:g}); "
                f"alert: beyond the {_pct(lv[1])} limit (p < {inner:g}).")
    q0, q1 = drawing.fdr_levels
    faceted = len(set(drawing.frame["panel"])) > 1
    scope = "within each panel" if faceted else f"across {drawing.n_tested} providers"
    watch = f"; watch: q < {drawing.fdr_watch:g}" if drawing.fdr_watch else ""
    return (f"Outlier: q < {q0:g}; alert: q < {q1:g}{watch} (Benjamini-Hochberg false discovery "
            f"rate {scope}, {tail} p-values). The curves show the {_pct(lv[0])} and "
            f"{_pct(lv[1])} limits, not adjusted for multiple comparisons.")


def _caption(drawing: Drawing) -> str | None:
    """The caller's caption or the flag rule, then every warning, which is never dropped."""
    candidates = [drawing.caption or _signal_caption(drawing), *drawing.warnings]
    lines = [line for line in candidates if line]
    return "<br>".join(lines) if lines else None


_CAPTION_TOP = 62


def _wrap_caption(caption: str, width: int | None) -> str:
    """Break each caption line to fit: a Plotly annotation does not wrap."""
    limit = max(60, int((width or 700) / 5.5) - 12)
    out = []
    for note in caption.split("<br>"):
        line = ""
        for word in note.split(" "):
            if line and len(line) + 1 + len(word) > limit:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}" if line else word
        out.append(line)
    return "<br>".join(out)


def _log_ticks(lo: float, hi: float) -> list[float]:
    """1-2-5 ticks across [lo, hi] on a log volume axis, each with its full label."""
    k0, k1 = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    for mults in ((1, 2, 5), range(1, 10)):
        vals = [m * 10.0 ** k for k in range(k0, k1 + 1) for m in mults]
        vals = [v for v in vals if lo <= v <= hi]
        if len(vals) >= 3:
            return vals
    return vals if len(vals) >= 2 else [lo, hi]


def _fmt_tick(v: float) -> str:
    return f"{v:,.0f}" if v >= 1 and float(v).is_integer() else f"{v:,.3g}"


def _configure_layout(fig, drawing: Drawing, opts, x_range_set: bool, fit_y: bool) -> None:
    apply_tufte_theme(fig)
    if opts["show_legend"]:
        legend = (dict(orientation="v", x=1.02, xanchor="left", y=1, yanchor="top")
                  if drawing.funnel else
                  dict(orientation="h", x=1, xanchor="right", y=1.02, yanchor="bottom"))
        fig.update_layout(showlegend=True, legend=dict(
            **legend, font=dict(size=11, color=TEXT_MUTED), bgcolor="rgba(0,0,0,0)"))
    frame = drawing.frame
    if opts.get("by_volume"):
        fig.update_xaxes(type="log" if opts.get("x_log") else "linear")
        fig.update_layout(hovermode="closest")
        if opts.get("x_log"):
            n = frame["pos"].to_numpy(dtype=float)
            n = n[np.isfinite(n) & (n > 0)]
            ticks = _log_ticks(float(n.min()), float(n.max()))
            fig.update_xaxes(tickvals=ticks, ticktext=[_fmt_tick(v) for v in ticks])
        fig.update_xaxes(nticks=0)
    else:
        categorical = all(isinstance(v, str) for v in frame["pos"])
        if categorical:
            fig.update_xaxes(type="category", nticks=0)
            order = opts.get("x_order")
            if isinstance(order, list):
                fig.update_xaxes(categoryorder="array", categoryarray=order)
            elif order is not None:
                fig.update_xaxes(categoryorder=order)
        else:
            fig.update_xaxes(nticks=5)
    if not opts["show_x_labels"]:
        fig.update_xaxes(showticklabels=False, ticks="")

    title = drawing.title
    if drawing.signals and title:
        title += " (signal)"
    if drawing.subtitle:
        title += f"<br><sup>{drawing.subtitle}</sup>"
    size = {k: opts[k] for k in ("height", "width") if opts.get(k) is not None}
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=TEXT), x=0, xanchor="left"),
        xaxis_title=drawing.xlab, yaxis_title=drawing.ylab,
        margin=dict(l=50, r=100, t=60 if drawing.title else 30, b=80), **size,
    )
    caption = _caption(drawing)
    if caption:
        caption = _wrap_caption(caption, opts.get("width"))
        lines = caption.count("<br>") + 1
        fig.update_layout(margin=dict(b=_CAPTION_TOP + 14 * lines + 8))
        fig.add_annotation(text=caption, xref="paper", yref="paper", x=0, y=0,
                           yshift=-_CAPTION_TOP, yanchor="top", showarrow=False,
                           font=dict(size=10, color=TEXT_FAINT), xanchor="left",
                           **({"align": "left"} if "<br>" in caption else {}))
    grid = GRID if opts["show_grid"] else "rgba(0,0,0,0)"
    fig.update_xaxes(showgrid=opts["show_grid"], gridcolor=grid)
    fig.update_yaxes(showgrid=opts["show_grid"], gridcolor=grid)
    if not opts["y_neg"]:
        fig.update_yaxes(rangemode="nonnegative")
    if opts["y_expand"] is not None and not fit_y:
        y = frame["y"].to_numpy(dtype=float)
        y = y[np.isfinite(y)]
        lo, hi = (float(y.min()), float(y.max())) if len(y) else (0.0, 0.0)
        e = opts["y_expand"]
        fig.update_yaxes(range=[min(lo, e) if opts["y_neg"] else max(0, min(lo, e)), max(hi, e) * 1.05])
    if drawing.percent:
        fig.update_yaxes(tickformat=".0%")
    if opts.get("x_angle") is not None:
        fig.update_xaxes(tickangle=opts["x_angle"])
    if opts.get("x_format") is not None:
        fig.update_xaxes(tickformat=opts["x_format"])
    if opts["flip"] and not x_range_set:
        fig.update_layout(xaxis=dict(autorange="reversed"))


# ---------------------------------------------------------------------------
# Pareto and Bernoulli CUSUM
# ---------------------------------------------------------------------------

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
