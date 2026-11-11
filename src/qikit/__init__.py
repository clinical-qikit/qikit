"""
qikit — statistical process control and funnel plots for healthcare quality.

Two questions, two functions, one vocabulary:

    from qikit import qic, funnel

    qic(df, x="month", y="deaths", n="admissions", chart="p")     # one measure over time
    funnel(df, y="deaths", n="expected", measure="oe", unit="surgeon")  # providers compared

Each returns a result: .brief() says what was found in a few lines, .to_table() is the
table to write back to a database (qikit.schema() lists its columns), .data and
.summary hold everything, and .plot() draws a Plotly figure. Start with
help(qikit.qic) or help(qikit.funnel): each opens with a table of which settings fit
which data. AGENTS.md (shipped with the package) maps the modules; docs/methods.md and
docs/qic-methods.md record every method and each departure from its source.

Minimum denominators: funnel(...).min_denominator(reliability=0.7) gives the volume at
which a provider's score is reliable, and funnel_rollup() compares reporting levels.

Also: funnel_sensitivity() (does a flag depend on the model?), paretochart(),
bchart() (Bernoulli CUSUM), and design() / analyze() for designed experiments.
"""

from .doe import ExperimentDesign, ExperimentResult, analyze, design
from .extras import bchart, paretochart
from .funnel import funnel, funnel_rollup, funnel_sensitivity
from .results import BChartResult, FunnelResult, ParetoResult, SPCResult
from .schema import schema
from .spc import qic

__version__ = "1.4.0"
__all__ = [
    "qic", "funnel", "funnel_sensitivity", "funnel_rollup", "schema", "SPCResult", "FunnelResult",
    "paretochart", "bchart", "ParetoResult", "BChartResult",
    "design", "analyze", "ExperimentDesign", "ExperimentResult", "__version__",
]
