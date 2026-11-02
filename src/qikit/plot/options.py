"""
options.py — what styles= can restyle, and the checks on display options.

Roles (styles={role: {attribute: value}}, or a list of such dicts merged in order, so a
house style is one constant: styles=[HOUSE, {...}]):

    data          the series line and routine points (color, width, name, opacity)
    outlier       points beyond the outer limits (color, name)
    alert         funnel points beyond the inner contour only (color, name)
    runs          points in a pattern the rules found (color, name)
    improving, concerning, neutral
                  method="nhs" special causes, by direction (color, name)
    cl, ucl, lcl, ucl_95, lcl_95, target
                  the reference lines (color, width, dash, visible, name)
    limits, limits_95
                  groups: ucl+lcl and ucl_95+lcl_95; a specific role overrides them
    end_labels    the CL/limit labels at the right-hand end (color, size)
    font          the figure's base font (family, size, color)

"name" renames a trace (its legend entry and end label too); "visible": False drops a
line and its end label.
"""

from __future__ import annotations

from typing import Any

_LINE_ATTRS = ("color", "width", "dash", "visible", "name")
_POINT_ATTRS = ("color", "name")
STYLE_ROLES: dict[str, tuple[str, ...]] = {
    "data": ("color", "width", "name", "opacity"),
    "outlier": _POINT_ATTRS, "alert": _POINT_ATTRS, "runs": _POINT_ATTRS,
    "improving": _POINT_ATTRS, "concerning": _POINT_ATTRS, "neutral": _POINT_ATTRS,
    "cl": _LINE_ATTRS, "ucl": _LINE_ATTRS, "lcl": _LINE_ATTRS,
    "ucl_95": _LINE_ATTRS, "lcl_95": _LINE_ATTRS, "target": _LINE_ATTRS,
    "end_labels": ("color", "size"),
    "font": ("family", "size", "color"),
}
# Group roles, applied before the specific ones so "ucl" can still override "limits".
STYLE_GROUPS: dict[str, tuple[str, ...]] = {
    "limits": ("ucl", "lcl"), "limits_95": ("ucl_95", "lcl_95"),
}
DASHES = ("solid", "dot", "dash", "longdash", "dashdot", "longdashdot")

# Which points on a time-ordered chart carry the runs color.
#   localized — the points forming a run or trend (default)
#   all       — every point, when the series as a whole crosses its center too rarely
#   none      — no runs color
RUNS_HIGHLIGHT = ("localized", "all", "none")
# Which flagged points get a text label: qic has outliers only; a funnel also alerts.
LABEL_SIGNALS = (None, "outlier", "alert", "both")


def merge_styles(layers: list | tuple) -> dict[str, dict]:
    """Merge a list of styles= dicts in order, later attributes winning role by role."""
    merged: dict[str, dict] = {}
    for layer in layers:
        if layer is None:
            continue
        if not isinstance(layer, dict):
            raise ValueError(f"each styles= layer must be a dict of role -> attributes, got "
                             f"{type(layer).__name__}.")
        for role, attrs in layer.items():
            if not isinstance(attrs, dict):
                raise ValueError(f"styles[{role!r}] must be a dict of attributes.")
            merged[role] = {**merged.get(role, {}), **attrs}
    return merged


def validate_styles(styles: dict | list | None) -> dict[str, dict]:
    """styles= expanded to one attribute dict per concrete role, each attribute checked."""
    if styles is None:
        return {}
    if isinstance(styles, (list, tuple)):
        styles = merge_styles(styles)
    if not isinstance(styles, dict):
        raise ValueError(f"styles must be a dict of role -> attributes (or a list of them), "
                         f"got {type(styles).__name__}.")
    valid = sorted(STYLE_ROLES) + sorted(STYLE_GROUPS)
    out: dict[str, dict] = {}
    for role in sorted(styles, key=lambda r: r not in STYLE_GROUPS):
        attrs = styles[role]
        targets: tuple[str, ...]
        allowed: tuple[str, ...]
        if role in STYLE_GROUPS:
            targets, allowed = STYLE_GROUPS[role], _LINE_ATTRS
        elif role in STYLE_ROLES:
            targets, allowed = (role,), STYLE_ROLES[role]
        else:
            hint = {"sigma": " (it is 'outlier' now)", "warn": " (it is 'alert' now)"}.get(role, "")
            raise ValueError(f"styles: unknown role {role!r}{hint}. Valid roles: {valid}.")
        if not isinstance(attrs, dict):
            raise ValueError(f"styles[{role!r}] must be a dict of attributes.")
        unknown = sorted(set(attrs) - set(allowed))
        if unknown:
            raise ValueError(f"styles[{role!r}]: unknown attribute(s) {unknown}. Valid for "
                             f"this role: {list(allowed)}.")
        for key, val in attrs.items():
            _check_attr(role, key, val)
        for target in targets:
            out.setdefault(target, {}).update(attrs)
    return out


def _check_attr(role: str, key: str, val) -> None:
    number = isinstance(val, (int, float)) and not isinstance(val, bool)
    if key == "opacity" and not (number and 0 < val <= 1):
        raise ValueError(f"styles[{role!r}]['opacity'] must be in (0, 1].")
    if key in ("width", "size") and not (number and val > 0):
        raise ValueError(f"styles[{role!r}][{key!r}] must be a positive number.")
    if key == "dash" and val not in DASHES:
        raise ValueError(f"styles[{role!r}]['dash'] must be one of {DASHES}, got {val!r}.")
    if key == "visible" and not isinstance(val, bool):
        raise ValueError(f"styles[{role!r}]['visible'] must be True or False.")
    if key in ("color", "name", "family") and not isinstance(val, str):
        raise ValueError(f"styles[{role!r}][{key!r}] must be a string.")


def validate_range(name: str, value: Any, numeric: bool) -> tuple | None:
    """An x_range= / y_range= pair (low, high); either end None means from the data."""
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__") or len(value) != 2:
        raise ValueError(f"{name} must be a (low, high) pair; either end may be None.")
    lo, hi = value
    for end in (lo, hi):
        if numeric and end is not None and (isinstance(end, bool) or not isinstance(end, (int, float))):
            raise ValueError(f"{name} ends must be numbers or None, got {end!r}.")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and not lo < hi:
        raise ValueError(f"{name} needs low < high, got {value!r}.")
    return (lo, hi)


def check_choice(name: str, value, valid: tuple):
    if value not in valid:
        raise ValueError(f"{name} must be one of {valid}, got {value!r}.")
    return value
