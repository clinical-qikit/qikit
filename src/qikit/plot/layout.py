"""
layout.py — axes, ranges, legend, captions and the figure layout around a Drawing.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ..core.pvalues import signal_thresholds
from .drawing import _SYMBOLS, Drawing, _line, _pct, _point_roles, _resolve_styles
from .options import validate_styles
from .theme import GRID, TEXT, TEXT_FAINT, TEXT_MUTED, apply_tufte_theme

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
