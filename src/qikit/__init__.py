"""
qikit — SPC charts and quality improvement tools for healthcare.

One function. One result object. One .plot() call.

    from qikit import qic
    result = qic(y=values, chart="i")
    result.plot()

References
----------
1. Montgomery DC. Introduction to Statistical Quality Control, 8th ed. Wiley, 2019.
2. Provost LP, Murray SK. The Health Care Data Guide, 2nd ed. Jossey-Bass, 2022.
"""

from .spc import (
    qic, 
    paretochart, 
    bchart, 
    SPCResult, 
    ParetoResult, 
    BChartResult
)
from .doe import (
    design, 
    analyze, 
    ExperimentDesign, 
    ExperimentResult
)

__version__ = "0.1.0a0"
__all__ = [
    "qic", "paretochart", "bchart", "SPCResult", "ParetoResult", "BChartResult",
    "design", "analyze", "ExperimentDesign", "ExperimentResult",
    "__version__"
]
