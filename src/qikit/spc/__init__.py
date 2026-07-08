"""
qikit.spc — SPC chart calculations, signal detection, and the qic() API.

One function. One result object. One .plot() call.

    from qikit import qic
    result = qic(y=values, chart="i")
    result.plot()
    result.data
    result.signals

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022. ISBN 978-1-119-69013-9, 978-1-119-69012-2.
3. Anhoej J, Olesen AV. Run charts revisited. PLoS ONE 9(11), 2014.
4. Anhoej J. Diagnostic value of run chart analysis. PLoS ONE 10(3), 2015.
5. Laney DB. Improved control charts for attributes. Quality Engineering 14(4), 2002.
"""

from __future__ import annotations

from .api import _print_summary, bchart, paretochart, qic
from .compute import compute
from .constants import A3, B3, B4, D2, D4
from .limits import CHARTS, ChartSpec, VALID_CHARTS
from .options import PlotOptions
from .results import BChartResult, ParetoResult, SPCResult
from .signals import _crossings_threshold, _longest_run_threshold, _runs_signals, _sigma_signals

__all__ = [
    "qic",
    "paretochart",
    "bchart",
    "SPCResult",
    "ParetoResult",
    "BChartResult",
    "PlotOptions",
]
