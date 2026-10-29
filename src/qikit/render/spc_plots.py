"""
spc_plots.py — Plotly rendering for SPCResult.

Design principles (Tufte, Visual Display of Quantitative Information):
- Maximize data-ink ratio; every pixel earns its place
- No plot border, no background fill, no y spine, minimal grid
- The series carries the darkest ink; reference lines are light hairlines
- Signal points: the only color — brick (sigma), amber (runs) — plus a
  diamond symbol on runs points so the distinction survives colorblindness
- Signal points are drawn larger than routine points
- CL/UCL/LCL labeled directly at right edge; no legend
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from qikit.spc.options import (
    DEFAULT_XLAB, VALID_LABEL_SIGNALS, VALID_RUNS_HIGHLIGHT,
    validate_range, validate_styles, validate_x_spacing,
)
from qikit.spc.pvalues import signal_thresholds
from qikit.spc.results import n_varies

from .utils import (
    apply_tufte_theme,
    NORMAL, CL, LIMIT, SIGMA, RUNS, TARGET, GRID, WARN, AXIS,
    TEXT, TEXT_MUTED, TEXT_FAINT,
)


def _resolve_runs_signal(df: Any, runs_highlight: str) -> np.ndarray:
    """
    Pick the runs-signal array the caller asked to highlight.

    "localized" drops the Anhoej crossings whole-series blanket, leaving only
    the points that form an actual run. Falls back to the plain runs_signal
    column for results built before runs_signal_localized existed.
    """
    if runs_highlight == "none":
        return np.zeros(len(df), dtype=bool)
    if runs_highlight == "localized" and "runs_signal_localized" in df.columns:
        return df["runs_signal_localized"].to_numpy()
    return df["runs_signal"].to_numpy()


def _amber_tier(
    df: Any, funnel: bool, show_95: bool, runs_highlight: str,
) -> tuple[np.ndarray, str]:
    """
    The points drawn amber, and the styles= role that colors them.

    A funnel has no time order, so runs carry nothing there (and are zeroed
    upstream); the amber tier goes to the 95% band instead. Only while that band is
    drawn, though: amber with no line to explain it would be color without a referent.
    """
    if funnel and show_95 and "warn_signal" in df.columns:
        return df["warn_signal"].to_numpy(), "warn"
    return _resolve_runs_signal(df, runs_highlight), "runs"


def _point_colors(
    sigma_sig: np.ndarray, runs_sig: np.ndarray,
    normal: str = NORMAL, sigma: str = SIGMA, amber: str = RUNS,
) -> list[str]:
    """Per-point colors: brick (sigma) > amber (runs or warn) > data ink (normal)."""
    return [
        sigma if s else amber if r else normal
        for s, r in zip(sigma_sig, runs_sig)
    ]


def _limit_names(chart_type: str, funnel: bool) -> tuple[tuple[str, str], tuple[str, str]]:
    """
    Default trace names for the outer and inner limit pairs. Funnel and O/E limits are
    probability contours, not sigma multiples, so naming them "UCL"/"2σ" would
    misreport what the reader is looking at.
    """
    if chart_type in ("oe", "oep") or funnel:
        return ("99.8%+", "99.8%-"), ("95%+", "95%-")
    return ("UCL", "LCL"), ("2σ+", "2σ-")


def _resolve_styles(styles: Any, chart_type: str, funnel: bool) -> dict[str, dict]:
    """
    Every styles= role with its defaults, overlaid with the caller's attributes. The
    defaults are exactly the figure drawn before styles= existed; a dash of None means
    the attribute is left unset, as it always was on the solid lines.
    """
    outer, inner = _limit_names(chart_type, funnel)
    line = {"width": 1, "dash": None, "visible": True}
    base: dict[str, dict] = {
        "data": {"color": NORMAL, "width": 1, "name": "data"},
        "sigma": {"color": SIGMA, "name": None},
        "warn": {"color": RUNS, "name": None},
        "runs": {"color": RUNS, "name": None},
        "cl": {**line, "color": CL, "name": "CL"},
        "ucl": {**line, "color": LIMIT, "name": outer[0]},
        "lcl": {**line, "color": LIMIT, "name": outer[1]},
        "ucl_95": {**line, "color": WARN, "dash": "dot", "name": inner[0]},
        "lcl_95": {**line, "color": WARN, "dash": "dot", "name": inner[1]},
        "target": {**line, "color": TARGET, "dash": "dot", "name": "Target"},
        "end_labels": {"color": TEXT_MUTED, "size": 10},
    }
    for role, attrs in validate_styles(styles).items():
        base[role] = {**base[role], **attrs}
    return base


def _line(style: dict) -> dict:
    """A Plotly line dict from a resolved line role."""
    out = {"color": style["color"], "width": style["width"]}
    if style.get("dash") is not None:
        out["dash"] = style["dash"]
    return out


def _point_symbols(sigma_sig: np.ndarray, runs_sig: np.ndarray) -> list[str]:
    """Per-point symbols for colorblind accessibility: circle (normal/sigma), diamond (runs)."""
    return [
        "diamond" if (r and not s) else "circle"
        for s, r in zip(sigma_sig, runs_sig)
    ]


def _point_sizes(sigma_sig: np.ndarray, runs_sig: np.ndarray, point_size: float) -> list[float]:
    """Signal points are drawn larger so exceptions carry more ink than routine ones."""
    base = point_size * 6
    return [
        base * 1.3 if (s or r) else base
        for s, r in zip(sigma_sig, runs_sig)
    ]


# Vertical offsets, in px, for the stacked levels of signal labels. Three levels
# clear a cluster of adjacent flagged points without a label drifting far enough
# from its point that the arrow has to do all the work.
_LABEL_LEVELS = (22, 38, 54)


def _signal_label_offsets(
    positions: list[float], above: list[bool], min_gap: float,
) -> list[tuple[int, int]]:
    """
    Arrow offsets (ax, ay) for signal labels, aligned with the inputs.

    Labels above the center line point up and those below point down, so the two
    sides never compete. Along each side, a label at most min_gap positions from
    the previous one steps to the next level (and alternates a small horizontal nudge);
    a gap resets it to the first level. Plotly cannot measure text, so this is a
    stagger rather than true collision detection — enough to keep a cluster of
    flagged neighbours legible.
    """
    out: list[tuple[int, int]] = [(0, 0)] * len(positions)
    for side in (True, False):
        idx = sorted(
            (i for i in range(len(positions)) if bool(above[i]) == side),
            key=lambda i: positions[i],
        )
        level, prev = 0, None
        for i in idx:
            close = prev is not None and positions[i] - prev <= min_gap
            level = (level + 1) % len(_LABEL_LEVELS) if close else 0
            ax = 0 if level == 0 else (12 if level % 2 else -12)
            ay = _LABEL_LEVELS[level]
            out[i] = (ax, -ay if side else ay)
            prev = positions[i]
    return out


def _fmt_p(v: Any) -> str:
    """A p- or q-value for the hover: two significant figures, floored for display."""
    if v is None or np.isnan(v):
        return "n/a"
    if v < 1e-4:
        return "<0.0001"
    return f"{v:.2g}"


# How the hover names the tail a p-value was taken from.
_SIDE_TEXT = {"above": "above", "below": "below", "both": "two-sided"}


def _fmt_hover(v: Any) -> str:
    """One hover_extra value as display text; pre-formatted for the same NaN reason as the O/E fields."""
    if v is None or (isinstance(v, (float, np.floating)) and np.isnan(v)):
        return "n/a"
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v))
    if isinstance(v, (float, np.floating)):
        return str(int(v)) if float(v).is_integer() else f"{float(v):g}"
    return str(v)


def _label_decimals(*arrays: np.ndarray) -> int:
    """
    Pick decimal places for the CL/UCL/LCL labels from the spread they span.

    Fixed decimals either round a proportion to nothing ("CL=0.2") or print
    noise on a large count ("CL=1284.0000"). Scaling to the limit spread keeps
    roughly three significant figures of whatever resolution the chart has.
    """
    vals = np.concatenate([np.asarray(a, dtype=float).ravel() for a in arrays if a is not None])
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return 1

    spread = float(np.max(vals) - np.min(vals))
    if spread <= 0:
        # A flat series has no spread to scale by; fall back to magnitude.
        spread = abs(float(vals[0])) or 1.0

    return int(np.clip(2 - math.floor(math.log10(spread)), 0, 4))


def _add_chart_traces(
    fig: go.Figure,
    df: Any,
    show_labels: bool,
    decimals: int | None,
    point_size: float,
    show_95: bool,
    x_pad: float,
    row: int | None = None,
    col: int | None = None,
    part_indices: list[int] | None = None,
    part_labels: list[str] | None = None,
    connect: bool | None = None,
    runs_highlight: str = "all",
    y_percent: bool = False,
    chart_type: str = "",
    funnel: bool = False,
    label_signals: str | None = None,
    x_spacing: str | None = None,
    hover_extra: list[str] | None = None,
    x_order: list | str | None = None,
    curve: Any = None,
    x_log: bool = False,
    x_title: str = "",
    signal_side: str = "both",
    styles: Any = None,
    legend: bool | None = None,
) -> dict[str, Any]:
    """
    Add data/CL/UCL/LCL traces, part boundaries, notes and signal labels to fig.

    x_spacing is already resolved. Under "n", curve is this panel's slice of
    result.funnel_limits(): the reference lines are drawn from it rather than at
    the points, and x_log puts every annotation on the log10 scale Plotly expects
    on a log axis. styles is the caller's styles= as given. legend is None when no
    legend is drawn (the traces are left exactly as before), else whether this
    panel's traces carry the legend entries.

    Returns what _fit_ranges needs to fit this panel's axes: the plotted points and
    the drawn reference lines.
    """
    st = _resolve_styles(styles, chart_type, funnel)
    x_raw = df["x"].tolist()
    labels = df["label"].tolist() if "label" in df.columns else None
    # What a reader should see for each point: its label when one was given, else x.
    display = [
        (labels[i] if labels and labels[i] else str(v)) for i, v in enumerate(x_raw)
    ]
    # Rank and volume spacing swap every x this function emits for a position or a
    # denominator, so no raw x value (a 10-digit ID, say) ever reaches the figure for
    # Plotly to coerce.
    rank = x_spacing == "rank"
    by_n = x_spacing == "n"
    if by_n:
        x = df["n"].astype(float).tolist()
    elif rank:
        x = list(range(1, len(x_raw) + 1))
    else:
        x = x_raw
    y = df["y"].to_numpy(dtype=float)
    cl = df["cl"].to_numpy(dtype=float)
    ucl = df["ucl"].to_numpy(dtype=float)
    lcl = df["lcl"].to_numpy(dtype=float)

    def _ax(v: Any) -> Any:
        """An x position as an annotation takes it: log10 of the value on a log axis."""
        if not x_log:
            return v
        # A zero denominator has no place on a log axis (its y is NaN anyway).
        return math.log10(v) if v > 0 else None

    # The reference lines. On a volume axis they are the funnel's contours, drawn on
    # a grid that includes every point's own n, so each curve passes through the limit
    # that decided that point; elsewhere they step from point to point.
    if by_n:
        ref_x = curve["n"].tolist()
        ref_cl, ref_ucl, ref_lcl = (curve[c].to_numpy(dtype=float) for c in ("cl", "ucl", "lcl"))
        ref_95 = (curve["ucl_95"].to_numpy(dtype=float), curve["lcl_95"].to_numpy(dtype=float))
    else:
        ref_x, ref_cl, ref_ucl, ref_lcl = x, cl, ucl, lcl
        ref_95 = (
            (df["ucl_95"].to_numpy(dtype=float), df["lcl_95"].to_numpy(dtype=float))
            if "ucl_95" in df and "lcl_95" in df else None
        )

    sigma_sig = df["sigma_signal"].to_numpy()
    warn_sig = (
        df["warn_signal"].to_numpy() if "warn_signal" in df.columns
        else np.zeros(len(df), dtype=bool)
    )
    amber, amber_role = _amber_tier(df, funnel, show_95, runs_highlight)
    amber_color = st[amber_role]["color"]
    colors = _point_colors(
        sigma_sig, amber, st["data"]["color"], st["sigma"]["color"], amber_color,
    )
    symbols = _point_symbols(sigma_sig, amber)
    sizes = _point_sizes(sigma_sig, amber, point_size)

    # Ghost points excluded via exclude=: faded and not counted toward
    # limits or signals (handled upstream in qikit.spc.compute/api).
    excluded = df["excluded"].to_numpy() if "excluded" in df.columns else np.zeros(len(x), dtype=bool)
    opacities = [0.35 if ex else 1.0 for ex in excluded]

    add_kwargs: dict[str, Any] = {}
    if row is not None and col is not None:
        add_kwargs = {"row": row, "col": col}

    def _legend(group: str | None = None, entry: bool = True) -> dict[str, Any]:
        """Legend settings for one trace; none at all when no legend is drawn."""
        if legend is None:
            return {}
        out: dict[str, Any] = {"showlegend": bool(legend and entry)}
        if group is not None:
            out["legendgroup"] = group
        return out

    # Connectivity: explicit override > auto-detection
    if connect is not None:
        mode = "lines+markers" if connect else "markers"
    else:
        is_categorical = all(isinstance(val, str) for val in x)
        sequential_patterns = ["-", "/", "week", "wk", "case", "obs", "pt"]
        looks_sequential = any(any(pat in str(val).lower() for pat in sequential_patterns) for val in x)
        dots_only = is_categorical and not looks_sequential
        mode = "markers" if dots_only else "lines+markers"

    # Data trace — zorder=2 keeps it above all reference ink
    text = df["notes"].tolist() if "notes" in df.columns else None
    ghost_note = ["excluded" if ex else "" for ex in excluded]
    extras = [c for c in (hover_extra or []) if c in df.columns]

    # Rank and volume modes plot positions or denominators, and labels replace the
    # key, so in any of these %{x} no longer names the point; the header is carried
    # in customdata instead. Appended last, so the O/E fields keep their indices.
    header = None
    if rank or by_n or labels:
        header = [
            f"{lab} ({v})" if (labels and lab) else str(v)
            for lab, v in zip(labels or [""] * len(x_raw), x_raw)
        ]
    hovertemplate = "{header}: %{y}"
    if text:
        hovertemplate += "<br>%{text}"

    if chart_type in ("oe", "oep") and "ci_95_lower" in df.columns:
        # An O/E ratio on its own tells a reader very little: 2.5 could be five deaths
        # against two expected or five hundred against two hundred, and only one of
        # those is worth a conversation. Lead with the counts, then the interval this
        # point's own data supports, then what it would have taken to flag — so a point
        # inside the limits reads as "not enough evidence" rather than "cleared".
        # Pre-formatted strings, because a d3 number format renders NaN literally.
        def _fmt(v: float, places: int) -> str:
            return "n/a" if v is None or np.isnan(v) else f"{v:.{places}f}"

        customdata = [
            [
                f" ({g})" if g else "",
                f"{_fmt(o, 0)} / expected {_fmt(e, 1)}",
                f"{_fmt(lo, 2)}–{_fmt(hi, 2)}",
                _fmt(d, 2),
            ]
            for g, o, e, lo, hi, d in zip(
                ghost_note,
                df["observed"], df["expected"],
                df["ci_95_lower"], df["ci_95_upper"], df["min_detectable_oe"],
            )
        ]
        hovertemplate += (
            "%{customdata[0]}"
            "<br>Observed %{customdata[1]}"
            "<br>95% CI: %{customdata[2]}"
            "<br>Smallest detectable O/E: %{customdata[3]}"
        )
    else:
        customdata = [[f" ({n})" if n else ""] for n in ghost_note]
        hovertemplate += "%{customdata[0]}"
        if by_n:
            # O/E already leads with its counts; a proportion or rate needs its
            # denominator, which the volume axis has taken over from the name.
            hovertemplate += f"<br>{x_title}: %{{x}}"

    if "p_value" in df.columns and "q_value" in df.columns:
        # Straight after the chart's own fields, so hover_extra and the header keep
        # their order behind it.
        k = len(customdata[0])
        side = _SIDE_TEXT.get(signal_side, signal_side)
        for row_cd, pv, qv in zip(customdata, df["p_value"], df["q_value"]):
            row_cd.append(f"{_fmt_p(pv)} ({side}), q = {_fmt_p(qv)}")
        hovertemplate += f"<br>p = %{{customdata[{k}]}}"

    for name in extras:
        k = len(customdata[0]) if customdata else 0
        for row_cd, v in zip(customdata, df[name]):
            row_cd.append(_fmt_hover(v))
        hovertemplate += f"<br>{name}: %{{customdata[{k}]}}"

    if header is not None:
        k = len(customdata[0]) if customdata else 0
        for row_cd, h in zip(customdata, header):
            row_cd.append(h)
        hovertemplate = hovertemplate.replace("{header}", f"%{{customdata[{k}]}}", 1)
    else:
        hovertemplate = hovertemplate.replace("{header}", "%{x}", 1)

    if customdata and len(customdata[0]) == 1:
        # The plain single-field form, unchanged from before multi-field hovers.
        customdata = [row_cd[0] for row_cd in customdata]
        hovertemplate = hovertemplate.replace("%{customdata[0]}", "%{customdata}")
    hovertemplate += "<extra></extra>"

    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode=mode,
        line=dict(color=st["data"]["color"], width=st["data"]["width"]),
        marker=dict(color=colors, symbol=symbols, size=sizes, line=dict(width=0), opacity=opacities),
        name=st["data"]["name"],
        text=text,
        customdata=customdata,
        hovertemplate=hovertemplate,
        connectgaps=False,
        cliponaxis=False,
        zorder=2,
        # Plotly draws a legend icon in the first point's color, which may be a
        # signal's; _add_legend_entries gives the series an entry of its own instead.
        **_legend("data", entry=False),
    ), **add_kwargs)

    # Target line
    if "target" in df:
        target = df["target"].to_numpy(dtype=float)
        has_target = not np.all(np.isnan(target))
        if has_target and st["target"]["visible"]:
            fig.add_trace(go.Scatter(
                x=x, y=target,
                mode="lines",
                line=_line(st["target"]),
                name=st["target"]["name"],
                hoverinfo="skip",
                zorder=1,
                **_legend(),
            ), **add_kwargs)

    # Center line
    if st["cl"]["visible"]:
        fig.add_trace(go.Scatter(
            x=ref_x, y=ref_cl,
            mode="lines",
            line=_line(st["cl"]),
            name=st["cl"]["name"],
            hoverinfo="skip",
            zorder=1,
            **_legend(),
        ), **add_kwargs)

    # The limit lines actually drawn, (values, upper side?), for _fit_ranges.
    drawn_limits: list[tuple[np.ndarray, bool]] = []

    # UCL/LCL — light solid hairlines; the direct labels say which is which,
    # so neither a dash pattern nor a fill between them has to carry meaning.
    # A legend shows each pair once: the upper line carries the entry for both.
    for arr, role in [(ref_ucl, "ucl"), (ref_lcl, "lcl")]:
        if not np.all(np.isnan(arr)) and st[role]["visible"]:
            fig.add_trace(go.Scatter(
                x=ref_x, y=arr,
                mode="lines",
                line=_line(st[role]),
                name=st[role]["name"],
                hoverinfo="skip",
                zorder=1,
                **_legend("limits", entry=role == "ucl" or not st["ucl"]["visible"]),
            ), **add_kwargs)
            drawn_limits.append((arr, role == "ucl"))

    # 2-sigma warning lines
    if show_95 and not np.all(np.isnan(ucl)):
        if ref_95 is not None:
            warn_upper, warn_lower = ref_95
        else:
            warn_upper = cl + (ucl - cl) * (2.0 / 3.0)
            warn_lower = cl - (ucl - cl) * (2.0 / 3.0)
        for warn_y, role in [(warn_upper, "ucl_95"), (warn_lower, "lcl_95")]:
            if not st[role]["visible"]:
                continue
            fig.add_trace(go.Scatter(
                x=ref_x, y=warn_y,
                mode="lines",
                line=_line(st[role]),
                name=st[role]["name"],
                hoverinfo="skip",
                zorder=1,
                **_legend("limits_95", entry=role == "ucl_95" or not st["ucl_95"]["visible"]),
            ), **add_kwargs)
            drawn_limits.append((np.asarray(warn_y, dtype=float), role == "ucl_95"))

    # Direct labels — work in both single and faceted mode
    if show_labels and len(x) > 0:
        # A percent axis displays 100x the stored value, so both the chosen
        # precision and the printed label follow the scale the reader sees.
        scale = 100.0 if y_percent else 1.0
        label_decimals = (
            decimals if decimals is not None
            else _label_decimals(ref_cl * scale, ref_ucl * scale, ref_lcl * scale)
        )
        value_fmt = f"{{:.{label_decimals}{'%' if y_percent else 'f'}}}"
        ann_kwargs: dict[str, Any] = {}
        if row is not None and col is not None:
            ann_kwargs = {"row": row, "col": col}
        for arr, role in [(ref_cl, "cl"), (ref_ucl, "ucl"), (ref_lcl, "lcl")]:
            if not st[role]["visible"]:
                continue
            label = st[role]["name"]
            valid_idx = np.flatnonzero(~np.isnan(arr))
            if len(valid_idx) == 0:
                continue
            # Anchor at the last point that actually has a value. For a stepped line
            # (variable n, or the S chart's c4(nᵢ)·σ̂ center) the label reads the value
            # at its own x, so a trailing gap must not drag it off the line.
            last = int(valid_idx[-1])
            val = float(arr[last])
            fig.add_annotation(
                x=_ax(ref_x[last]), y=val,
                text=f"{label}={value_fmt.format(val)}",
                xshift=8 + x_pad * 4,
                showarrow=False, xanchor="left",
                font=dict(size=st["end_labels"]["size"], color=st["end_labels"]["color"]),
                **ann_kwargs,
            )

    # Part boundary lines
    if part_indices:
        for boundary_1based in part_indices:
            boundary_0idx = boundary_1based - 1
            if 0 <= boundary_0idx < len(x):
                x_val = x[boundary_0idx]
                label_text = None
                if part_labels:
                    try:
                        idx = part_indices.index(boundary_1based)
                        label_text = part_labels[idx]
                    except (ValueError, IndexError):
                        pass

                fig.add_vline(
                    x=x_val,
                    line=dict(color=LIMIT, width=1),
                    annotation_text=label_text or "",
                    annotation_position="top",
                    annotation_font=dict(size=9, color=TEXT_FAINT),
                    **add_kwargs
                )

    # Signal labels. A labeled point's note joins its label rather than getting an
    # annotation of its own, so the two can never land on top of each other.
    notes_list = [str(v) for v in df["notes"]] if "notes" in df.columns else [""] * len(x)
    labeled: set[int] = set()
    if label_signals is not None and len(x) > 0:
        flagged = np.zeros(len(x), dtype=bool)
        if label_signals in ("outlier", "both"):
            flagged |= sigma_sig.astype(bool)
        if label_signals in ("warn", "both"):
            flagged |= warn_sig.astype(bool)
        idx = [int(i) for i in np.flatnonzero(flagged) if np.isfinite(y[i])]
        if by_n:
            # Neighbours on a volume axis are close in axis units, not in rank: many
            # small providers crowd its left end. Rescaled to 0…K, so min_gap below
            # keeps its meaning of a fifteenth of the plot.
            coord = np.array([_ax(v) for v in x], dtype=float)
            finite = coord[np.isfinite(coord)]
            lo, hi = (float(finite.min()), float(finite.max())) if len(finite) else (0.0, 0.0)
            positions = (
                [(coord[i] - lo) / (hi - lo) * len(x) for i in idx] if hi > lo else idx
            )
        elif isinstance(x_order, list) and not rank:
            order_pos = {v: k for k, v in enumerate(x_order)}
            positions = [order_pos.get(x_raw[i], i) for i in idx]
        else:
            positions = idx
        above = [bool(np.isnan(cl[i]) or y[i] >= cl[i]) for i in idx]
        # A label is roughly a fifteenth of a typical plot's width, so neighbours
        # closer than that, in points, would print over each other on one level.
        min_gap = max(1, math.ceil(len(x) / 15))
        offsets = _signal_label_offsets(positions, above, min_gap)
        ann_kwargs = {"row": row, "col": col} if (row is not None and col is not None) else {}
        for i, (ax, ay) in zip(idx, offsets):
            note = notes_list[i].strip()
            fig.add_annotation(
                x=_ax(x[i]), y=y[i],
                text=f"{display[i]} — {note}" if note else display[i],
                showarrow=True, arrowhead=0,
                arrowcolor=AXIS, arrowwidth=1,
                font=dict(size=10, color=st["sigma"]["color"] if sigma_sig[i] else amber_color),
                ax=ax, ay=ay,
                **ann_kwargs,
            )
            labeled.add(i)

    # Note annotations
    if "notes" in df.columns:
        for i, note in enumerate(notes_list):
            if i in labeled:
                continue
            if note.strip():
                fig.add_annotation(
                    x=_ax(x[i]), y=y[i],
                    text=note,
                    showarrow=True, arrowhead=1,
                    arrowcolor=AXIS, arrowwidth=1,
                    font=dict(size=9, color=TEXT_MUTED),
                    ax=0, ay=-25,
                    **add_kwargs
                )

    # Tick text: positions need names, and given labels outrank the raw key on a
    # categorical axis. A numeric, date or volume axis keeps its own scale.
    if not by_n and (rank or (labels and all(isinstance(v, str) for v in x_raw))):
        fig.update_xaxes(tickvals=x, ticktext=display, **add_kwargs)

    return {
        "row": row, "col": col, "x": x, "y": y,
        "ref_x": ref_x, "cl": np.asarray(ref_cl, dtype=float), "limits": drawn_limits,
    }


# Padding on an axis end the data decides, as a share of the span; an end the
# caller gave is used as given.
_X_PAD = 0.02
_Y_PAD = 0.05


def _x_coords(values: Any) -> tuple[Any, bool]:
    """
    Plotted x values in a comparable form: floats, or datetimes (True) on a date axis.
    Missing values come back NaN / NaT, which every range test treats as outside.
    """
    vals = list(values)
    if all(
        v is None or (isinstance(v, (int, float, np.number)) and not isinstance(v, bool))
        for v in vals
    ):
        return np.array([np.nan if v is None else float(v) for v in vals]), False
    return pd.to_datetime(pd.Series(vals, dtype=object), errors="coerce").to_numpy(), True


def _within(coords: Any, lo: Any, hi: Any) -> np.ndarray:
    """Which coords fall inside [lo, hi]; an end of None is open."""
    c = np.asarray(coords)
    mask = ~pd.isna(c)
    if lo is not None:
        mask &= c >= lo
    if hi is not None:
        mask &= c <= hi
    return np.asarray(mask, dtype=bool)


def _fit_ranges(
    panels: list[dict[str, Any]], x_range: Any, y_range: Any, x_log: bool,
    y_neg: bool, y_expand: float | None, shared_y: bool,
) -> tuple[tuple | None, list[tuple] | None]:
    """
    Axis ranges for x_range= / y_range=: (x bounds or None, per-panel y bounds or None).

    The y axis is fitted, wherever x_range is set or y_range leaves an end open, to
    the points inside the x range, the center line there, and each drawn limit's
    in-range value nearest the center line. That last term keeps a funnel's narrow
    high-volume end in view while its low-volume flare, like the trimmed points, no
    longer stretches the axis. y_neg=False floors the fit at 0 and y_expand widens it
    to include that value, as they do without a range; an end the caller gave wins.
    """
    if x_range is None and y_range is None:
        return None, None
    x_bounds = None
    if x_range is not None:
        is_date = _x_coords(panels[0]["x"])[1]
        conv = pd.Timestamp if is_date else float
        lo, hi = (None if v is None else conv(v) for v in x_range)
        if x_log and any(v is not None and v <= 0 for v in (lo, hi)):
            raise ValueError("x_range on a log axis needs positive ends.")
        if lo is None or hi is None:
            data = np.concatenate([
                np.asarray(_x_coords(p[key])[0]) for p in panels for key in ("x", "ref_x")
            ])
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
        cl = p["cl"]
        vals += list(cl[ref_inside & np.isfinite(cl)])
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


def _apply_ranges(
    fig: go.Figure, panels: list[dict[str, Any]], x_bounds: tuple | None,
    y_bounds: list[tuple] | None, x_log: bool, flip: bool,
) -> None:
    """Write _fit_ranges' bounds to the axes; a log axis takes log10 of its ends."""
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


def _add_legend_entries(
    fig: go.Figure, result: Any, styles: Any, funnel: bool, show_95: bool,
    runs_highlight: str, point_size: float,
) -> None:
    """
    Legend-only markers for the series and for each signal color the figure draws:
    the point colors live on the one data trace, so without these a legend could not
    say what red or amber means, and would draw the series in whatever color its first
    point happens to be. The series entry shares the data trace's legendgroup, so
    clicking it still hides the points. Signal entries are named for what decided
    them, unless styles= names them.
    """
    df = result.data
    st = _resolve_styles(styles, result.chart_type, funnel)
    drawn = np.isfinite(df["y"].to_numpy(dtype=float))
    sigma = df["sigma_signal"].to_numpy().astype(bool) & drawn
    amber, amber_role = _amber_tier(df, funnel, show_95, runs_highlight)
    amber = np.asarray(amber, dtype=bool) & ~sigma & drawn
    contour = result.chart_type in ("oe", "oep") or funnel
    method = _signal_setting(result, "signal_method", "limits")
    outer, inner = signal_thresholds(_signal_setting(result, "signal_side", "both"))
    stat = {"exact": "p", "fdr": "q"}.get(method)
    defaults = {
        "sigma": f"{stat} < {outer:g}" if stat else (
            "Beyond 99.8%" if contour else "Beyond UCL/LCL"
        ),
        "warn": f"{stat} < {inner:g}" if stat else "Beyond 95%",
        "runs": "Run signal",
    }
    size = point_size * 6
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers",
        marker=dict(color=st["data"]["color"], symbol="circle", size=size),
        name=st["data"]["name"], legendgroup="data",
        showlegend=True, hoverinfo="skip", legendrank=1,  # first, before the lines
    ))
    for role, present, symbol in (
        ("sigma", sigma.any(), "circle"), (amber_role, amber.any(), "diamond"),
    ):
        if not present:
            continue
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(color=st[role]["color"], symbol=symbol, size=size * 1.3),
            name=st[role]["name"] or defaults[role],
            showlegend=True, hoverinfo="skip",
        ))


def _log_ticks(lo: float, hi: float) -> list[float]:
    """
    Tick values for a log volume axis: 1-2-5 steps across [lo, hi], or every digit when
    the range is too narrow for those, or the two ends as a last resort.

    Plotly's own log ticks label the steps inside a decade with their leading digit
    alone, so 20, 30, … 90 read as "2, 3, … 9" beside "100". Explicit values carry
    their full labels.
    """
    k0, k1 = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    for mults in ((1, 2, 5), range(1, 10)):
        vals = [m * 10.0 ** k for k in range(k0, k1 + 1) for m in mults]
        vals = [v for v in vals if lo <= v <= hi]
        if len(vals) >= 3:
            return vals
    return vals if len(vals) >= 2 else [lo, hi]


def _fmt_tick(v: float) -> str:
    return f"{v:,.0f}" if v >= 1 and float(v).is_integer() else f"{v:,.3g}"


# Shown under an underpowered O/E funnel when the caller supplied no caption of their
# own. summary["underpowered"] is enough for code, but these charts get screenshotted
# into credentialing packets, and no summary key travels with the image — the caveat
# has to be part of the picture.
_UNDERPOWERED_CAPTION = (
    "Most points lack the volume to detect a doubling of risk; absence of a signal "
    "is not evidence of acceptable performance."
)


def _signal_setting(result: Any, key: str, default: Any = None) -> Any:
    """
    A funnel's signal_side / signal_method from its summary. A faceted result keeps
    them at the top level too, but fall back to the first panel's for a result built
    without them.
    """
    summary = getattr(result, "summary", None) or {}
    if key in summary:
        return summary[key]
    for sub in (summary.get("by_facet") or {}).values():
        if key in sub:
            return sub[key]
    return default


def _signal_caption(result: Any, show_95: bool, funnel: bool) -> str | None:
    """
    Say what flagged the points when the drawn contours did not. Under
    signal_method="exact"/"fdr" a point beyond a line can be unflagged and the colours
    answer a different question from the curves; a screenshot carries no summary keys,
    so the figure has to say so itself.
    """
    method = _signal_setting(result, "signal_method", "limits")
    if method == "limits":
        return None
    side = _signal_setting(result, "signal_side", "both")
    outer, inner = signal_thresholds(side)
    if method == "exact":
        tail = "two-sided" if side == "both" else f"one-sided ({side} the center line)"
        test, stat = f"exact {tail} test", "p"
    else:
        summary = getattr(result, "summary", None) or {}
        if "by_facet" in summary:
            scope = "within each panel"
        else:
            scope = f"across {summary.get('n_tested', 0)} points"
        test, stat = f"Benjamini–Hochberg false discovery rate {scope}", "q"
    # Amber marks the warn tier only on a funnel drawn with its 95% band.
    amber = show_95 and funnel
    levels = f"{stat} < {outer:g} (red)" + (f", {stat} < {inner:g} (amber)" if amber else "")
    curves = "99.8% and 95% limits" if show_95 else "99.8% limits"
    tail_note = (
        "for reference" if method == "exact" else "not adjusted for multiple comparisons"
    )
    return f"Signals: {test}, {levels}. The curves show the {curves}, {tail_note}."


def _effective_caption(result: Any, show_95: bool = False, funnel: bool = False) -> str | None:
    """
    The caller's caption, or, when they gave none, every automatic note that applies:
    what flagged the points (signal_method="exact"/"fdr") and the underpowered warning.
    """
    caption = getattr(result, "caption", None)
    if caption:
        return caption
    summary = getattr(result, "summary", None) or {}
    notes = [
        _signal_caption(result, show_95, funnel),
        _UNDERPOWERED_CAPTION if summary.get("underpowered") else None,
    ]
    notes = [n for n in notes if n]
    return "<br>".join(notes) if notes else None


def _configure_layout(
    fig: go.Figure,
    result: Any,
    show_grid: bool,
    y_neg: bool,
    y_expand: float | None,
    y_percent: bool,
    x_angle: int | None,
    x_format: str | None,
    flip: bool,
    x_order: list | str | None = None,
    height: int | None = None,
    width: int | None = None,
    x_nticks_all: bool = False,
    show_x_labels: bool = True,
    x_spacing: str | None = None,
    x_log: bool = False,
    x_title: str = "",
    show_95: bool = False,
    funnel: bool = False,
    show_legend: bool = False,
    x_range_set: bool = False,
    fit_y: bool = False,
) -> None:
    """
    Shared layout and axis styling for single and faceted plots. x_range_set and fit_y
    say that _apply_ranges will write the axis ranges, so flip= and y_expand= leave
    them to it.
    """
    apply_tufte_theme(fig)
    if show_legend:
        # Above the plot, right-aligned: clear of the left-aligned title and of the
        # end labels down the right edge.
        fig.update_layout(
            showlegend=True,
            legend=dict(
                orientation="h", x=1, xanchor="right", y=1.02, yanchor="bottom",
                font=dict(size=11, color=TEXT_MUTED), bgcolor="rgba(0,0,0,0)",
            ),
        )

    # Categorical x-axis: explicit type + optional ordering
    x_vals = result.data["x"].tolist()
    is_categorical = all(isinstance(v, str) for v in x_vals)
    if x_spacing in ("rank", "n"):
        # Positions or denominators, not categories. The unified hover would title
        # itself with that number, so hover the nearest point and let it name itself.
        is_categorical = False
        fig.update_xaxes(type="log" if x_log else "linear")
        fig.update_layout(hovermode="closest")
        if x_log:
            n_vals = result.data["n"].to_numpy(dtype=float)
            n_vals = n_vals[np.isfinite(n_vals) & (n_vals > 0)]
            ticks = _log_ticks(float(n_vals.min()), float(n_vals.max()))
            # A caller's x_format still decides how the labels read.
            text = None if x_format is not None else [_fmt_tick(v) for v in ticks]
            fig.update_xaxes(tickvals=ticks, ticktext=text)
    elif is_categorical:
        fig.update_xaxes(type="category")
        if x_order is not None:
            if isinstance(x_order, list):
                fig.update_xaxes(categoryorder="array", categoryarray=x_order)
            else:
                fig.update_xaxes(categoryorder=x_order)

    # nticks: restrict x ticks only for numeric/time axes; for categorical, show all or limit
    if x_nticks_all or is_categorical:
        fig.update_xaxes(nticks=0)  # 0 = Plotly auto, shows all category labels
    else:
        fig.update_xaxes(nticks=5)

    if not show_x_labels:
        # The category axis and %{x} in the hovertemplate keep the full label
        # available on hover, so this is purely a subtraction of axis ink.
        fig.update_xaxes(showticklabels=False, ticks="")

    title_text = result.title
    if hasattr(result, "signals") and result.signals and title_text:
        title_text += " ⚠"

    full_title = title_text
    if hasattr(result, "subtitle") and result.subtitle:
        full_title += f"<br><sup>{result.subtitle}</sup>"

    top_margin = 30 if not result.title else 60
    size_kwargs: dict[str, Any] = {}
    if height is not None:
        size_kwargs["height"] = height
    if width is not None:
        size_kwargs["width"] = width

    fig.update_layout(
        title=dict(text=full_title, font=dict(size=15, color=TEXT), x=0, xanchor="left"),
        xaxis_title=x_title,
        yaxis_title=result.ylab,
        margin=dict(l=50, r=100, t=top_margin, b=80),
        **size_kwargs,
    )

    caption = _effective_caption(result, show_95, funnel)
    if caption:
        fig.add_annotation(
            text=caption, xref="paper", yref="paper",
            x=0, y=-0.2, showarrow=False,
            font=dict(size=10, color=TEXT_FAINT), xanchor="left",
            # Plotly centers each line of a multi-line annotation on the widest.
            **({"align": "left"} if "<br>" in caption else {}),
        )

    grid_color = GRID if show_grid else "rgba(0,0,0,0)"
    fig.update_xaxes(showgrid=show_grid, gridcolor=grid_color)
    fig.update_yaxes(showgrid=show_grid, gridcolor=grid_color)

    if not y_neg:
        fig.update_yaxes(rangemode="nonnegative")
    
    if y_expand is not None and not fit_y:
        y_vals = result.data["y"].to_numpy(dtype=float)
        y_valid = y_vals[~np.isnan(y_vals)]
        curr_min = np.nanmin(y_valid) if len(y_valid) > 0 else 0
        curr_max = np.nanmax(y_valid) if len(y_valid) > 0 else 0
        new_min = min(curr_min, y_expand) if y_neg else max(0, min(curr_min, y_expand))
        new_max = max(curr_max, y_expand)
        fig.update_yaxes(range=[new_min, new_max * 1.05])

    if y_percent:
        fig.update_yaxes(tickformat=".0%")
    if x_angle is not None:
        fig.update_xaxes(tickangle=x_angle)
    if x_format is not None:
        fig.update_xaxes(tickformat=x_format)
    if flip and not x_range_set:
        fig.update_layout(xaxis=dict(autorange="reversed"))


def _plot_faceted(
    result: Any,
    nrow: int | None,
    ncol: int | None,
    scales: str,
    show_labels: bool,
    show_95: bool,
    decimals: int | None,
    point_size: float,
    x_angle: int | None,
    x_pad: float,
    x_format: str | None,
    y_expand: float | None,
    y_neg: bool,
    y_percent: bool,
    flip: bool,
    show_grid: bool,
    x_order: list | str | None = None,
    height: int | None = None,
    width: int | None = None,
    connect: bool | None = None,
    x_nticks_all: bool = False,
    runs_highlight: str = "all",
    show_x_labels: bool = True,
    funnel: bool = False,
    label_signals: str | None = None,
    x_spacing: str | None = None,
    hover_extra: list[str] | None = None,
    curve: Any = None,
    x_log: bool = False,
    x_title: str = "",
    x_range: Any = None,
    y_range: Any = None,
    styles: Any = None,
    show_legend: bool = False,
) -> go.Figure:
    """Render a faceted SPCResult as a multi-panel Plotly Figure."""
    facet_vals = list(result.data["facet"].unique())
    n_facets = len(facet_vals)

    if ncol is None and nrow is None:
        ncol = min(3, n_facets)
        nrow = math.ceil(n_facets / ncol)
    elif ncol is None:
        ncol = math.ceil(n_facets / nrow)
    elif nrow is None:
        nrow = math.ceil(n_facets / ncol)

    shared_y = (scales == "fixed")
    fig = make_subplots(
        rows=nrow, cols=ncol,
        shared_xaxes=True,
        shared_yaxes=shared_y,
        horizontal_spacing=0.06,
        vertical_spacing=0.10,
        subplot_titles=[str(v) for v in facet_vals],
    )

    # make_subplots writes the panel titles as annotations; restyle them before
    # traces append their own (direct labels, notes) to this same list.
    for ann in fig.layout.annotations:
        ann.font = dict(size=11, color=TEXT_MUTED)

    panels = []
    for idx, fv in enumerate(facet_vals):
        r_row = idx // ncol + 1
        r_col = idx % ncol + 1
        df_sub = result.data[result.data["facet"] == fv]

        panels.append(_add_chart_traces(
            fig, df_sub,
            show_labels=show_labels,
            decimals=decimals,
            point_size=point_size,
            show_95=show_95,
            x_pad=x_pad,
            row=r_row, col=r_col,
            connect=connect,
            runs_highlight=runs_highlight,
            y_percent=y_percent,
            chart_type=result.chart_type,
            funnel=funnel,
            label_signals=label_signals,
            x_spacing=x_spacing,
            hover_extra=hover_extra,
            x_order=x_order,
            curve=None if curve is None else curve[curve["facet"] == fv],
            x_log=x_log,
            x_title=x_title,
            signal_side=_signal_setting(result, "signal_side", "both"),
            styles=styles,
            # One set of legend entries for the figure, from the first panel.
            legend=(idx == 0) if show_legend else None,
        ))

    if show_legend:
        _add_legend_entries(fig, result, styles, funnel, show_95, runs_highlight, point_size)
    x_bounds, y_bounds = _fit_ranges(
        panels, x_range, y_range, x_log, y_neg, y_expand, shared_y=scales == "fixed",
    )
    _configure_layout(
        fig, result, show_grid, y_neg, y_expand,
        y_percent, x_angle, x_format, flip, x_order=x_order,
        height=height, width=width, x_nticks_all=x_nticks_all,
        show_x_labels=show_x_labels, x_spacing=x_spacing,
        x_log=x_log, x_title=x_title, show_95=show_95, funnel=funnel,
        show_legend=show_legend, x_range_set=x_bounds is not None,
        fit_y=y_bounds is not None,
    )
    _apply_ranges(fig, panels, x_bounds, y_bounds, x_log, flip)

    # Shared axes hide the tick labels on inner panels; the tick marks left
    # behind carry no information, so drop them. Runs after _configure_layout,
    # which re-applies ticks="outside" to every axis.
    for axis_name in fig.layout:
        if axis_name.startswith(("xaxis", "yaxis")) and fig.layout[axis_name].showticklabels is False:
            fig.layout[axis_name].ticks = ""

    return fig


def plot_pareto(result: Any, x_angle: int | None = None, **_kwargs: Any) -> go.Figure:
    """Render a ParetoResult as a Plotly Figure."""
    df = result.data
    
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Bars
    fig.add_trace(
        go.Bar(
            x=df["category"], 
            y=df["count"], 
            name=result.ylab,
            marker_color=NORMAL,
            hovertemplate="%{x}: %{y}<extra></extra>"
        ),
        secondary_y=False,
    )
    
    # Cumulative line
    fig.add_trace(
        go.Scatter(
            x=df["category"], 
            y=df["cum_percent"], 
            name="Cumulative %",
            mode="lines+markers",
            line=dict(color=SIGMA, width=2),
            marker=dict(size=6),
            hovertemplate="%{x}: %{y:.1f}%<extra></extra>"
        ),
        secondary_y=True,
    )
    
    # Build title with subtitle if present
    full_title = result.title
    if hasattr(result, "subtitle") and result.subtitle:
        full_title += f"<br><sup>{result.subtitle}</sup>"

    fig.update_layout(
        title=dict(text=full_title, font=dict(size=14)),
        xaxis_title=result.xlab,
        yaxis_title=result.ylab,
        yaxis2_title="Cumulative %",
        margin=dict(l=50, r=50, t=60, b=80),
    )
    apply_tufte_theme(fig)
    
    if hasattr(result, "caption") and result.caption:
        fig.add_annotation(
            text=result.caption,
            xref="paper", yref="paper",
            x=0, y=-0.2,
            showarrow=False,
            font=dict(size=10, color="#777"),
            xanchor="left",
        )
    
    fig.update_yaxes(range=[0, df["count"].sum() * 1.05], secondary_y=False)
    fig.update_yaxes(range=[0, 105], ticksuffix="%", secondary_y=True)
    
    if x_angle is not None:
        fig.update_xaxes(tickangle=x_angle)
        
    fig.update_xaxes(showline=True, linecolor=AXIS)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, secondary_y=False)

    return fig


def plot_bchart(result: Any, **_kwargs: Any) -> go.Figure:
    """Render a BChartResult as a Plotly Figure."""
    df = result.data
    limit = result.limit
    limit2 = -limit
    
    fig = go.Figure()
    
    # Upward CUSUM
    fig.add_trace(go.Scatter(
        x=df["x"], y=df["cusum_up"],
        mode="lines",
        line=dict(color=NORMAL, width=1.5),
        name="CUSUM Up",
        hovertemplate="Case %{x}<br>CUSUM Up: %{y:.2f}<extra></extra>"
    ))
    
    # Downward CUSUM
    fig.add_trace(go.Scatter(
        x=df["x"], y=df["cusum_down"],
        mode="lines",
        line=dict(color=NORMAL, width=1.5, dash="dot"),
        name="CUSUM Down",
        hovertemplate="Case %{x}<br>CUSUM Down: %{y:.2f}<extra></extra>"
    ))
    
    # Signals
    sig_up = df[df["signal_up"]]
    if not sig_up.empty:
        fig.add_trace(go.Scatter(
            x=sig_up["x"], y=[limit] * len(sig_up),
            mode="markers",
            marker=dict(color=SIGMA, size=10, symbol="triangle-up"),
            name="Signal Up",
            hoverinfo="skip"
        ))
        
    sig_down = df[df["signal_down"]]
    if not sig_down.empty:
        fig.add_trace(go.Scatter(
            x=sig_down["x"], y=[limit2] * len(sig_down),
            mode="markers",
            marker=dict(color=SIGMA, size=10, symbol="triangle-down"),
            name="Signal Down",
            hoverinfo="skip"
        ))

    # Threshold lines
    fig.add_hline(y=limit, line=dict(color=CL, width=1, dash="dash"))
    fig.add_hline(y=limit2, line=dict(color=CL, width=1, dash="dash"))
    fig.add_hline(y=0, line=dict(color=CL, width=1))
    
    # Build title with subtitle if present
    full_title = result.title
    if hasattr(result, "subtitle") and result.subtitle:
        full_title += f"<br><sup>{result.subtitle}</sup>"

    fig.update_layout(
        title=dict(text=full_title, font=dict(size=14)),
        xaxis_title=result.xlab,
        yaxis_title=result.ylab,
        margin=dict(l=50, r=50, t=60, b=80),
    )
    apply_tufte_theme(fig)
    
    if hasattr(result, "caption") and result.caption:
        fig.add_annotation(
            text=result.caption,
            xref="paper", yref="paper",
            x=0, y=-0.2,
            showarrow=False,
            font=dict(size=10, color="#777"),
            xanchor="left",
        )
    
    fig.update_xaxes(showline=True, linecolor=AXIS)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False)

    return fig


def plot_result(
    result: Any,
    show_grid: bool = False,
    show_labels: bool = True,
    show_95: bool = False,
    decimals: int | None = None,
    point_size: float = 1.5,
    x_angle: int | None = None,
    x_pad: float = 1.0,
    x_format: str | None = None,
    y_expand: float | None = None,
    y_neg: bool = True,
    y_percent: bool = False,
    flip: bool = False,
    nrow: int | None = None,
    ncol: int | None = None,
    scales: str = "fixed",
    part_labels: list[str] | None = None,
    part_indices: list[int] | None = None,
    x_order: list | str | None = None,
    height: int | None = None,
    width: int | None = None,
    connect: bool | None = None,
    x_nticks_all: bool = False,
    runs_highlight: str = "all",
    show_x_labels: bool = True,
    funnel: bool = False,
    label_signals: str | None = None,
    x_spacing: str | None = None,
    hover_extra: list[str] | None = None,
    x_log: bool = False,
    xlab_given: bool = True,
    n_name: str | None = None,
    x_range: Any = None,
    y_range: Any = None,
    styles: Any = None,
    show_legend: bool = False,
    **_kwargs: Any,
) -> go.Figure:
    """
    Render an SPCResult as a Plotly Figure.
    """
    # plot(**overrides) bypasses qic(), so these are the only guards on that path.
    if runs_highlight not in VALID_RUNS_HIGHLIGHT:
        raise ValueError(
            f"runs_highlight must be one of {VALID_RUNS_HIGHLIGHT}, got {runs_highlight!r}."
        )
    if label_signals not in VALID_LABEL_SIGNALS:
        raise ValueError(
            f"label_signals must be one of {VALID_LABEL_SIGNALS}, got {label_signals!r}."
        )
    if label_signals in ("warn", "both") and "warn_signal" not in result.data.columns:
        raise ValueError(
            f"label_signals={label_signals!r} needs the 95% warn tier, which only "
            f"chart='oe'/'oep' and funnel=True p/pp/u/up charts have. "
            f"Use label_signals='outlier' here."
        )
    # The same rule qic() applied, re-run because an override can change any input.
    x_spacing = validate_x_spacing(
        x_spacing, funnel, n_varies(result.data), x_order, x_log,
    )
    validate_styles(styles)
    x_range = validate_range("x_range", x_range, numeric=False)
    y_range = validate_range("y_range", y_range, numeric=True)
    if (
        x_range is not None and x_spacing == "x"
        and all(isinstance(v, str) for v in result.data["x"])
    ):
        raise ValueError(
            "x_range= needs a numeric, date, rank or volume axis, and this x axis is "
            "categorical. Plotly ranges a category axis by position, so pass "
            "x_spacing='rank' to range by position, or x_order= to choose categories."
        )
    curve = result.funnel_limits() if x_spacing == "n" else None
    # A title the caller gave is theirs on any axis; otherwise it names the axis drawn,
    # which an x_spacing override may have changed since qic() resolved result.xlab.
    if xlab_given:
        x_title = result.xlab
    else:
        x_title = n_name if (x_spacing == "n" and n_name) else DEFAULT_XLAB

    if "facet" in result.data.columns:
        return _plot_faceted(
            result, nrow=nrow, ncol=ncol, scales=scales,
            show_labels=show_labels, show_95=show_95,
            decimals=decimals, point_size=point_size,
            x_angle=x_angle, x_pad=x_pad, x_format=x_format,
            y_expand=y_expand, y_neg=y_neg, y_percent=y_percent,
            flip=flip, show_grid=show_grid, x_order=x_order,
            height=height, width=width,
            connect=connect, x_nticks_all=x_nticks_all,
            runs_highlight=runs_highlight,
            show_x_labels=show_x_labels,
            funnel=funnel, label_signals=label_signals,
            x_spacing=x_spacing, hover_extra=hover_extra,
            curve=curve, x_log=x_log, x_title=x_title,
            x_range=x_range, y_range=y_range, styles=styles, show_legend=show_legend,
        )

    df = result.data
    fig = go.Figure()

    panel = _add_chart_traces(
        fig, df,
        show_labels=show_labels,
        decimals=decimals,
        point_size=point_size,
        show_95=show_95,
        x_pad=x_pad,
        part_indices=part_indices,
        part_labels=part_labels,
        connect=connect,
        runs_highlight=runs_highlight,
        y_percent=y_percent,
        chart_type=result.chart_type,
        funnel=funnel,
        label_signals=label_signals,
        x_spacing=x_spacing,
        hover_extra=hover_extra,
        x_order=x_order,
        curve=curve,
        x_log=x_log,
        x_title=x_title,
        signal_side=_signal_setting(result, "signal_side", "both"),
        styles=styles,
        legend=True if show_legend else None,
    )

    if show_legend:
        _add_legend_entries(fig, result, styles, funnel, show_95, runs_highlight, point_size)
    x_bounds, y_bounds = _fit_ranges(
        [panel], x_range, y_range, x_log, y_neg, y_expand, shared_y=True,
    )
    _configure_layout(
        fig, result, show_grid, y_neg, y_expand,
        y_percent, x_angle, x_format, flip, x_order=x_order,
        height=height, width=width, x_nticks_all=x_nticks_all,
        show_x_labels=show_x_labels, x_spacing=x_spacing,
        x_log=x_log, x_title=x_title, show_95=show_95, funnel=funnel,
        show_legend=show_legend, x_range_set=x_bounds is not None,
        fit_y=y_bounds is not None,
    )
    _apply_ranges(fig, [panel], x_bounds, y_bounds, x_log, flip)

    return fig
