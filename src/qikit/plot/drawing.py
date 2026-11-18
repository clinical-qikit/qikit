"""
drawing.py — the Drawing that every SPC and funnel figure is built from, the plot()
options each accepts, and how styles= and point roles resolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .options import LABEL_SIGNALS, RUNS_HIGHLIGHT, check_choice, validate_range, validate_styles
from .theme import (
    CL,
    CONCERNING,
    CONTOUR,
    IMPROVING,
    LIMIT,
    NEUTRAL,
    NORMAL,
    RUNS,
    SIGMA,
    TARGET,
    TEXT_MUTED,
    WARN,
    WATCH,
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
