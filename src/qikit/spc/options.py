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

# Which flagged points get a text label next to them.
#   outlier — points beyond the outer limits (sigma_signal)
#   warn    — points in the 95% tier only (warn_signal)
#   both    — either
#   None    — no point labels (the CL/limit labels are governed by show_labels)
VALID_LABEL_SIGNALS = (None, "outlier", "warn", "both")

# How points are spaced along x.
#   None — auto: "n" on a funnel whose denominators vary, "x" everywhere else
#   x    — by x value: categorical for strings, numeric/date otherwise
#   rank — evenly, in row order, with the x values (or point_labels) as tick text
#   n    — by denominator (expected events on oe/oep), with the limits drawn as
#          smooth contours across the volume range [Spiegelhalter 2005, §2]
VALID_X_SPACING = (None, "x", "rank", "n")

# The x title when the caller gives none and the axis is not the volume axis.
DEFAULT_XLAB = "Subgroup"


def resolve_x_spacing(x_spacing: str | None, funnel: bool, n_varies: bool) -> str:
    """
    The spacing a figure is actually drawn with; qic() and plot() share this rule.

    A funnel defaults to its volume axis, which is how Spiegelhalter draws one. The
    one exception is a funnel whose denominators are all equal: there is nothing to
    spread, and every point would stack on one vertical line.
    """
    if x_spacing is not None:
        return x_spacing
    return "n" if (funnel and n_varies) else "x"


def validate_x_spacing(
    x_spacing: str | None, funnel: bool, n_varies: bool,
    x_order: object, x_log: bool,
) -> str:
    """Resolve x_spacing and reject combinations that cannot be drawn; returns it."""
    if x_spacing not in VALID_X_SPACING:
        raise ValueError(
            f"x_spacing must be one of {VALID_X_SPACING}, got {x_spacing!r}."
        )
    spacing = resolve_x_spacing(x_spacing, funnel, n_varies)
    if spacing == "rank" and x_order is not None:
        raise ValueError(
            "x_order= cannot be combined with x_spacing='rank': rank spacing plots "
            "points in their row order, so there is no category order left to set."
        )
    if spacing == "n":
        if not funnel:
            raise ValueError(
                "x_spacing='n' needs funnel=True: it plots each point against its "
                "denominator, which only a funnel orders by."
            )
        if not n_varies:
            raise ValueError(
                "x_spacing='n' needs denominators that vary: with every n equal, all "
                "points would stack on one vertical line. Use x_spacing='x'."
            )
        if x_order is not None:
            raise ValueError(
                "x_order= orders categories, but this funnel spaces points by their "
                "denominator (x_spacing='n', the funnel default). Pass x_spacing='x' "
                "to order them by x_order=."
            )
    if x_log and spacing != "n":
        raise ValueError(
            f"x_log=True needs the volume axis (x_spacing='n'), but this chart is "
            f"spaced by {spacing!r}."
        )
    return spacing


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
    label_signals: str | None = None
    x_spacing: str | None = None
    x_log: bool = False
    # Whether the caller titled the x axis. When not, the title follows the spacing
    # drawn: n_name on the volume axis, DEFAULT_XLAB otherwise. True by default so
    # an SPCResult built by hand keeps its own xlab.
    xlab_given: bool = True
    n_name: str | None = None  # the denominator's name; funnels only
    hover_extra: list[str] = field(default_factory=list)
    funnel: bool = False
    x_nticks_all: bool = False
