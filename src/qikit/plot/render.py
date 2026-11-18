"""
render.py — one renderer for every Drawing: panels, points, lines, labels and
tooltips.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .drawing import _SYMBOLS, Drawing, _line, _point_roles, _resolve_styles
from .layout import _add_legend_entries, _apply_ranges, _configure_layout, _fit_ranges
from .options import validate_styles
from .theme import AXIS, LIMIT, TEXT_FAINT, TEXT_MUTED


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
                "rate": ("events", "exposure"), "mean": ("total", "cases"),
                }.get(str(drawing.measure), ("numerator", "denominator"))
        smallest = {"oe": "Smallest detectable O/E", "mean": "Smallest detectable mean",
                    }.get(str(drawing.measure), "Smallest detectable")
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
