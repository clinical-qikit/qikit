"""
options.py — display-only params for qic(), single source of truth for _plot_opts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlotOptions:
    """Display-only params for qic(), single source of truth for _plot_opts."""
    show_labels: bool = True
    show_95: bool = False
    show_grid: bool = False
    decimals: int = 1
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
    x_nticks_all: bool = False
