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

# What styles= can restyle, and which attributes each role takes. Defaults live with
# the renderer (render/spc_plots.py), which owns the palette.
#   data       — the series line and routine markers
#   sigma      — sigma_signal markers and their labels
#   warn       — the amber 95%-tier markers and labels (a funnel drawn with show_95)
#   runs       — runs-signal markers and labels (time-ordered charts)
#   cl, ucl, lcl, ucl_95, lcl_95, target — the reference lines
#   end_labels — the CL/limit labels at the right-hand end of each line
#   font       — the figure's base font (family, size, color)
# data also takes "opacity" for the points (a funnel defaults to 0.85, so overlapping
# providers stay visible).
# "name" renames a trace (its legend entry and end label too); on the signal roles it
# names the legend-only entry show_legend adds. "visible": False drops a line and its
# end label from the figure.
_LINE_ATTRS = ("color", "width", "dash", "visible", "name")
_POINT_ATTRS = ("color", "name")
STYLE_ROLES: dict[str, tuple[str, ...]] = {
    "data": ("color", "width", "name", "opacity"),
    "sigma": _POINT_ATTRS, "warn": _POINT_ATTRS, "runs": _POINT_ATTRS,
    "cl": _LINE_ATTRS, "ucl": _LINE_ATTRS, "lcl": _LINE_ATTRS,
    "ucl_95": _LINE_ATTRS, "lcl_95": _LINE_ATTRS, "target": _LINE_ATTRS,
    "end_labels": ("color", "size"),
    "font": ("family", "size", "color"),
}
# Group roles, applied before the specific ones so "ucl" can still override "limits".
STYLE_ALIASES: dict[str, tuple[str, ...]] = {
    "limits": ("ucl", "lcl"), "limits_95": ("ucl_95", "lcl_95"),
}
VALID_DASHES = ("solid", "dot", "dash", "longdash", "dashdot", "longdashdot")


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


def merge_styles(layers: list | tuple) -> dict[str, dict]:
    """
    Merge a list of styles= dicts in order, later attributes winning role by role, so
    a house style and a per-chart tweak compose: styles=[HOUSE, {"ucl": {...}}].
    """
    merged: dict[str, dict] = {}
    for layer in layers:
        if layer is None:
            continue
        if not isinstance(layer, dict):
            raise ValueError(
                f"each styles= layer must be a dict of role -> attributes, got "
                f"{type(layer).__name__}."
            )
        for role, attrs in layer.items():
            if not isinstance(attrs, dict):
                raise ValueError(f"styles[{role!r}] must be a dict of attributes.")
            merged[role] = {**merged.get(role, {}), **attrs}
    return merged


def validate_styles(styles: dict | None) -> dict[str, dict]:
    """
    Check styles= and expand it to one attribute dict per concrete role.

    Group roles ("limits", "limits_95") apply first and a specific role overrides
    them, so {"limits": {"width": 2}, "ucl": {"color": "red"}} gives ucl both. Only
    the caller's own attributes come back; the renderer supplies the defaults.
    """
    if styles is None:
        return {}
    if isinstance(styles, (list, tuple)):
        styles = merge_styles(styles)
    if not isinstance(styles, dict):
        raise ValueError(
            f"styles must be a dict of role -> attributes (or a list of them, merged in "
            f"order), got {type(styles).__name__}."
        )
    valid_roles = sorted(STYLE_ROLES) + sorted(STYLE_ALIASES)
    out: dict[str, dict] = {}
    for role in sorted(styles, key=lambda r: r not in STYLE_ALIASES):
        attrs = styles[role]
        if role in STYLE_ALIASES:
            targets, allowed = STYLE_ALIASES[role], _LINE_ATTRS
        elif role in STYLE_ROLES:
            targets, allowed = (role,), STYLE_ROLES[role]
        else:
            raise ValueError(f"styles: unknown role {role!r}. Valid roles: {valid_roles}.")
        if not isinstance(attrs, dict):
            raise ValueError(f"styles[{role!r}] must be a dict of attributes.")
        unknown = sorted(set(attrs) - set(allowed))
        if unknown:
            raise ValueError(
                f"styles[{role!r}]: unknown attribute(s) {unknown}. "
                f"Valid for this role: {list(allowed)}."
            )
        for key, val in attrs.items():
            if key == "opacity" and not (
                isinstance(val, (int, float)) and not isinstance(val, bool) and 0 < val <= 1
            ):
                raise ValueError(f"styles[{role!r}]['opacity'] must be in (0, 1].")
            if key in ("width", "size") and not (
                isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0
            ):
                raise ValueError(f"styles[{role!r}][{key!r}] must be a positive number.")
            if key == "dash" and val not in VALID_DASHES:
                raise ValueError(
                    f"styles[{role!r}]['dash'] must be one of {VALID_DASHES}, got {val!r}."
                )
            if key == "visible" and not isinstance(val, bool):
                raise ValueError(f"styles[{role!r}]['visible'] must be True or False.")
            if key in ("color", "name") and not isinstance(val, str):
                raise ValueError(f"styles[{role!r}][{key!r}] must be a string.")
        for target in targets:
            out.setdefault(target, {}).update(attrs)
    return out


def validate_range(name: str, value: object, numeric: bool) -> tuple | None:
    """
    Check an x_range= / y_range= pair: (low, high), either end None for "from the
    data". numeric demands numbers (y always; x may be dates).
    """
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__") or len(value) != 2:
        raise ValueError(f"{name} must be a (low, high) pair; either end may be None.")
    lo, hi = value
    for end in (lo, hi):
        if numeric and end is not None and (
            isinstance(end, bool) or not isinstance(end, (int, float))
        ):
            raise ValueError(f"{name} ends must be numbers or None, got {end!r}.")
    if (
        isinstance(lo, (int, float)) and isinstance(hi, (int, float))
        and not lo < hi
    ):
        raise ValueError(f"{name} needs low < high, got {value!r}.")
    return (lo, hi)


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
    # Kept as the caller wrote them; validate_styles/validate_range run at render too,
    # because plot(**overrides) bypasses qic().
    x_range: tuple | None = None
    y_range: tuple | None = None
    styles: dict | None = None
    show_legend: bool = False
