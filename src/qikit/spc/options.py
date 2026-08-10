"""
options.py — display-only params for qic(), single source of truth for _plot_opts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Which runs-signal points get point-level coloring.
#   all       — every point the runs method flagged (includes the Anhoej
#               crossings whole-series pattern)
#   localized — only the points forming an actual run; the crossings blanket
#               is suppressed (still reported in summary["crossings_signal"])
#   none      — no runs coloring; sigma outliers are unaffected
VALID_RUNS_HIGHLIGHT = ("all", "localized", "none")


@dataclass(frozen=True)
class PlotOptions:
    """Display-only params for qic(), single source of truth for _plot_opts."""
    show_labels: bool = True
    show_95: bool = False
    show_grid: bool = False
    show_x_labels: bool = True
    decimals: int | None = None  # None = scale to the limit spread
    point_size: float = 1.5
    x_angle: int | None = None
    x_pad: float = 1.0
    x_period: str | None = None
    x_format: str | None = None
    x_order: list | str | None = None
    y_neg: bool = True
    y_percent: bool | None = None
    y_percent_accuracy: int | None = None
    y_expand: float | None = None
    flip: bool = False
    strip_horizontal: bool = False
    nrow: int | None = None
    ncol: int | None = None
    scales: str = "fixed"
    part_labels: list[str] | None = None
    part_indices: list[int] = field(default_factory=list)
    height: int | None = None
    width: int | None = None
    connect: bool | None = None
    runs_highlight: str = "localized"
    x_nticks_all: bool = False
