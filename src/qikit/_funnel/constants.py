"""
_funnel/constants.py — choices, defaults and internal column names shared by the funnel modules.
"""

from __future__ import annotations

from ..schema import FUNNEL_COLUMNS

MEASURES = ("oe", "proportion", "rate", "mean")
SIGNALS = ("limits", "fdr")
BENCHMARKS = (None, "abc", "eb")
COMPARE_TO = (None, "peers", "model")
DEFAULT_FDR_LEVELS = (0.05, 0.10)
_SIDES = {None: "both", "higher": "above", "lower": "below"}

# Column names funnel() writes to result.data; hover= columns must avoid them.
_COLUMNS = tuple(c.name for c in FUNNEL_COLUMNS)

# Internal working columns on the normalized frame.
_UNIT, _Y, _N, _LABEL, _EXCL = "__unit", "__y", "__n", "__label", "__exclude"
_CASES, _SS, _MAXY, _MAXN, _PHI = "__cases", "__sum_sq", "__max_y", "__max_n", "__phi"
_DROP = "__dropped"

# fragility scans at most this many of a unit's worst cases (methods §4.15).
_FRAGILITY_MAX = 50

# How a funnel draws, for the parts of qikit's own engine contract that funnel() keeps
# private: Byar limits on O/E exist for the shared fixtures with the TypeScript engine.
_LIMIT_METHODS = ("exact", "byar")

_RENAMED = {
    "test_min_expected": "fdr_min_denominator=",
    "signal_side": "worse= ('higher', 'lower' or None)",
    "signal_method": "signal=",
    "levels": "limits=",
    "cl": "center=",
    "point_labels": "label=",
    "hover_extra": "hover=",
}
_DISPLAY = (
    "title", "subtitle", "caption", "xlab", "ylab", "label_signals", "styles", "x_log",
    "x_range", "y_range", "show_legend", "width", "height",
)
