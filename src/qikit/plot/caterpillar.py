"""
caterpillar.py — the caterpillar plot: shrunk estimates with their intervals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .charts import _display, _funnel_ylab, _panels
from .pareto import _simple_layout
from .render import _fmt_hover
from .theme import CL, CONTOUR, IMPROVING, NORMAL, SIGMA, TEXT_FAINT, TEXT_MUTED

_CATERPILLAR_OPTIONS = dict(
    title="", subtitle=None, caption=None, xlab=None, ylab=None, top=None, bottom=None,
    label_flagged=None, show_legend=True, width=None, height=None, styles=None,
    decimals=None,
)
# Caterpillar roles: each estimate_flag value, and the reference line.
_FLAG_COLORS = {"worse": SIGMA, "better": IMPROVING, "higher": SIGMA, "lower": IMPROVING,
                "no different": NORMAL, None: TEXT_FAINT}
_FLAG_NAMES = {"worse": "Worse", "better": "Better", "higher": "Higher", "lower": "Lower",
               "no different": "No different", None: "No interval"}
_CATERPILLAR_ROLES = {"worse", "better", "higher", "lower", "no_different", "raw",
                      "reference"}
# Above this many rows per panel, only flagged providers are named on the axis.
_CATERPILLAR_LABEL_ALL = 60


def plot_caterpillar(result, **given) -> go.Figure:
    """
    Draw a FunnelResult's shrunk estimates with their intervals, one row per provider
    sorted by eb_rate (see FunnelResult.plot). Ranks are uncertain even when real
    differences exist (Marshall & Spiegelhalter 1998), so the intervals, not the order,
    carry the reading.
    """
    unknown = sorted(set(given) - set(_CATERPILLAR_OPTIONS))
    if unknown:
        raise TypeError(f"plot(kind='caterpillar') got unexpected keyword argument(s) "
                        f"{unknown}. Valid names: {sorted(_CATERPILLAR_OPTIONS)}.")
    opts = {**_CATERPILLAR_OPTIONS, **given}
    for name in ("top", "bottom"):
        v = opts[name]
        if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and v > 0):
            raise ValueError(f"{name}= is a number of providers (a whole number above 0), "
                             f"got {v!r}.")
    styles = opts["styles"] or {}
    if not isinstance(styles, dict) or set(styles) - _CATERPILLAR_ROLES:
        raise ValueError(f"styles= on a caterpillar plot takes roles "
                         f"{sorted(_CATERPILLAR_ROLES)}, each a dict with color= or name=.")
    d, meta, s = result.data, result._meta, result.summary
    facets = meta.get("facets", [])
    if "eb_low" not in d:
        raise ValueError("This result has no shrunk-estimate columns to draw.")
    frame = d.assign(
        _panel=_panels(d, facets),
        _display=_display(d["label"] if "label" in d else None, d["unit"]),
    )
    panels = list(dict.fromkeys(frame["_panel"]))
    by_facet = s.get("by_facet") or {}
    refs = {p: (by_facet.get(p, s) if p is not None else s).get("reference") for p in panels}

    groups = []
    for p in panels:
        in_panel = np.array([v == p if p is not None else v is None for v in frame["_panel"]])
        g = frame[in_panel].sort_values("eb_rate", kind="stable")
        if opts["top"] or opts["bottom"]:
            keep = pd.Series(False, index=g.index)
            if opts["bottom"]:
                keep.iloc[:opts["bottom"]] = True
            if opts["top"]:
                keep.iloc[-opts["top"]:] = True
            g = g[keep.to_numpy()]
        groups.append((p, g))
    gap_after = {}   # top=/bottom=: a blank row between the two ends of a panel
    for p, g in groups:
        full = int(np.sum([v == p if p is not None else v is None for v in frame["_panel"]]))
        b = opts["bottom"] or 0
        gap_after[p] = b if (opts["top"] and opts["bottom"] and len(g) < full) else None
    heights = [max(len(g), 1) for _, g in groups]
    fig = make_subplots(rows=len(groups), cols=1, shared_xaxes=True,
                        row_heights=[h / sum(heights) for h in heights],
                        vertical_spacing=0.06 if len(groups) > 1 else 0.0,
                        subplot_titles=[p for p, _ in groups] if facets else None)
    m = meta.get("multiply", 1.0)
    pct = meta.get("measure") == "proportion" and m == 1.0
    fmt = (lambda v: f"{v:.1%}") if pct else (lambda v: _fmt_hover(v))
    seen: set = set()
    for row, (p, g) in enumerate(groups, start=1):
        pos = np.arange(len(g), dtype=float)
        if gap_after[p] is not None:
            pos[gap_after[p]:] += 1.0
        flags = list(g["estimate_flag"])
        names = g["_display"].to_numpy()
        label_all = (opts["label_flagged"] is False
                     or (opts["label_flagged"] is None and len(g) <= _CATERPILLAR_LABEL_ALL))
        ticktext = [str(n) if label_all or f not in (None, "no different") else ""
                    for n, f in zip(names, flags)]
        hover = [
            f"<b>{n}</b><br>volume {_fmt_hover(v)}<br>raw {fmt(r)}<br>estimate {fmt(e)}"
            f"<br>{meta.get('interval', 0.95):.0%} interval {fmt(lo)} to {fmt(hi)}"
            f"<br>P(worse than reference) {'' if not np.isfinite(pw) else f'{pw:.2f}'}"
            for n, v, r, e, lo, hi, pw in zip(
                names, g["denominator"], g["y"], g["eb_rate"], g["eb_low"], g["eb_high"],
                g["prob_worse"].astype(float))
        ]
        # The raw value, faint, so the pull toward the prior shows.
        raw_style = styles.get("raw", {})
        fig.add_trace(go.Scatter(
            x=g["y"], y=pos, mode="markers", hoverinfo="skip",
            marker=dict(size=5, color=raw_style.get("color", CONTOUR), opacity=0.45,
                        symbol="circle-open"),
            name=raw_style.get("name", "Raw value"), legendgroup="raw",
            showlegend=opts["show_legend"] and "raw" not in seen,
        ), row=row, col=1)
        seen.add("raw")
        for flag in dict.fromkeys(flags):
            idx = [i for i, f in enumerate(flags) if f == flag]
            role = styles.get("no_different" if flag == "no different" else flag or "", {})
            color = role.get("color", _FLAG_COLORS[flag])
            gi = g.iloc[idx]
            xs, ys = [], []
            for lo, hi, y in zip(gi["eb_low"], gi["eb_high"], pos[idx]):
                xs += [lo, hi, None]
                ys += [y, y, None]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", hoverinfo="skip",
                                     line=dict(color=color, width=1.6), showlegend=False,
                                     legendgroup=str(flag)), row=row, col=1)
            fig.add_trace(go.Scatter(
                x=gi["eb_rate"], y=pos[idx], mode="markers",
                marker=dict(size=6, color=color,
                            symbol="diamond" if flag not in (None, "no different") else "circle"),
                name=role.get("name", _FLAG_NAMES[flag]), legendgroup=str(flag),
                showlegend=opts["show_legend"] and flag not in seen,
                text=[hover[i] for i in idx], hovertemplate="%{text}<extra></extra>",
            ), row=row, col=1)
            seen.add(flag)
        ref = refs[p]
        if ref is not None and np.isfinite(ref):
            rs = styles.get("reference", {})
            fig.add_vline(x=ref, line=dict(color=rs.get("color", CL), width=1, dash="dot"),
                          row=row, col=1)
        top_pos = float(pos[-1]) + 1.0 if len(pos) else 0.0
        fig.update_yaxes(tickvals=list(pos), ticktext=ticktext, range=[-1, top_pos],
                         tickfont=dict(size=9 if len(g) > 30 else 11, color=TEXT_MUTED),
                         row=row, col=1)
    n_rows = sum(heights)
    model = any((by_facet.get(p, s) if p is not None else s).get("compare_to") == "model"
                or s.get("compare_to") == "model" for p in panels)
    xlab = opts["xlab"] if opts["xlab"] is not None else (
        f"{_funnel_ylab(meta)}, shrunk estimate with "
        f"{meta.get('interval', 0.95):.0%} interval")
    caption = opts["caption"] if opts["caption"] is not None else (
        "Dotted line: " + ("1.0, the risk model's expected" if model else "the center line")
        + ". Open circles: raw values; markers: shrunk estimates, pulled toward the "
        + ("pooled value" if model else "center") + " most at low volume. Ranks are "
        "uncertain: read the intervals, not the order.")
    _simple_layout(fig, opts["title"], opts["subtitle"], caption, xlab,
                   opts["ylab"] or "", opts["width"],
                   opts["height"] or int(min(4000, 120 + 14 * n_rows + 40 * len(groups))))
    fig.update_layout(margin=dict(b=130), showlegend=opts["show_legend"], hovermode="closest",
                      legend=dict(orientation="h", y=1.0, yanchor="bottom", x=1,
                                  xanchor="right", font=dict(size=11, color=TEXT_MUTED)))
    fig.update_yaxes(showgrid=False)
    if pct:
        fig.update_xaxes(tickformat=".0%")
    return fig
