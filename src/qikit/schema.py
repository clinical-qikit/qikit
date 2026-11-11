"""
schema.py — every column qic() and funnel() can write to result.data, in order.

    import qikit
    qikit.schema("funnel")        # column, dtype, always, meaning

result.data holds the columns a call produced; some appear only with the option that
makes them (label=, part=, benchmark=). result.to_table() holds every column listed
here, in this order and with these types, empty where the call did not produce it: the
fixed shape a database table or a Snowpark RETURNS TABLE clause needs.
"""

from __future__ import annotations

from typing import NamedTuple

import pandas as pd


class Column(NamedTuple):
    name: str
    dtype: str      # "float", "int", "bool", "string", or "any" (the caller's own type)
    always: bool    # in result.data on every call; else only with the option that makes it
    meaning: str


QIC_COLUMNS = (
    Column("x", "any", True, "the period or subgroup, in plotted order"),
    Column("label", "string", False, "display name of the point (label=)"),
    Column("y", "float", True, "the plotted value, after multiply="),
    Column("n", "float", False, "denominator (n=), or the subgroup size on xbar and s charts"),
    Column("cl", "float", True, "center line"),
    Column("ucl", "float", True, "upper 3-sigma control limit"),
    Column("lcl", "float", True, "lower 3-sigma control limit"),
    Column("ucl_95", "float", True, "upper 2-sigma line"),
    Column("lcl_95", "float", True, "lower 2-sigma line"),
    Column("signal", "string", True, '"outlier" beyond ucl or lcl, else "none"'),
    Column("runs_signal", "bool", True, "part of a pattern the rules found (a run, a trend)"),
    Column("variation", "string", False,
           'method="nhs": "improving", "concerning", "neutral" or "common"'),
    Column("special_cause", "string", False, 'method="nhs": the rule that fired at this point'),
    Column("part", "string", False, "which part of the chart the point belongs to (part=)"),
    Column("baseline", "bool", True, "used to set the center line and limits"),
    Column("excluded", "bool", True, "left out of the limits and the rules (exclude=)"),
    Column("target", "float", False, "the target line (target=), after multiply="),
    Column("notes", "string", False, "annotation for the point (notes=)"),
)

FUNNEL_COLUMNS = (
    Column("unit", "any", True, "provider identifier"),
    Column("label", "string", False, "display name of the provider (label=)"),
    Column("y", "float", True, "the plotted value: O/E, proportion, rate or mean, after multiply="),
    Column("numerator", "float", True, "the summed y= input"),
    Column("denominator", "float", True, "the summed n= input"),
    Column("effective_denominator", "float", False,
           "denominator / phi_i under a within_dispersion column: the x axis"),
    Column("cl", "float", True, "center line"),
    Column("lower_outlier", "float", True, "outer contour, lower (99.8% by default)"),
    Column("upper_outlier", "float", True, "outer contour, upper"),
    Column("lower_alert", "float", True, "inner contour, lower (95% by default)"),
    Column("upper_alert", "float", True, "inner contour, upper"),
    Column("p_value", "float", True, "against the model the contours are drawn from"),
    Column("q_value", "float", True, "Benjamini-Hochberg adjustment within the chart"),
    Column("signal", "string", True, '"outlier", "alert" or "none"'),
    Column("direction", "string", True, '"higher" or "lower": side of the center line'),
    Column("min_detectable", "float", True,
           "smallest true value this provider could have flagged with 80% power"),
    Column("ci_lower", "float", True, "exact 95% interval for the provider's own value, lower"),
    Column("ci_upper", "float", True, "exact 95% interval, upper"),
    Column("excluded", "bool", True, "left out of the center, dispersion and testing"),
    Column("raw_excess", "float", True, "numerator - cl * denominator, positive is worse"),
    Column("reliability", "float", True, "shrinkage weight, 0 to 1"),
    Column("eb_rate", "float", True, "shrunk (empirical Bayes) value"),
    Column("eb_excess", "float", True, "shrunk excess over the reference; sort on this"),
    Column("prob_worse", "float", True, "posterior probability the true value is worse"),
    Column("eb_low", "float", True, "posterior interval for the true value, lower"),
    Column("eb_high", "float", True, "posterior interval, upper"),
    Column("estimate_flag", "string", True,
           'where the interval lies against the reference: "worse", "better", '
           '"higher", "lower" or "no different"'),
    Column("p_value_drop1", "float", True, "p-value without the single most extreme case"),
    Column("flag_survives_drop1", "bool", True, "whether the flag survives dropping that case"),
    Column("fragility", "int", True, "how many worst cases removed before the flag is lost"),
    Column("benchmark_group", "bool", False, 'benchmark="abc": among the best performers pooled'),
    Column("benchmark", "float", False, "the goal (benchmark=), the same on every row of a facet"),
    Column("meets_benchmark", "bool", False, "the provider's own value is at the goal or better"),
)

_SCHEMAS = {"qic": QIC_COLUMNS, "funnel": FUNNEL_COLUMNS}
_PANDAS = {"float": "float64", "int": "Int64", "bool": "boolean"}


def schema(function: str) -> pd.DataFrame:
    """
    The columns of result.data for "qic" or "funnel": column, dtype ("float", "int",
    "bool", "string", or "any" for the caller's own type), always (False when the column
    needs the option that makes it), and meaning. result.to_table() returns exactly
    these, in this order, after the facets= columns and before the hover= columns.
    """
    if function not in _SCHEMAS:
        raise ValueError(f"schema() takes 'qic' or 'funnel', got {function!r}.")
    return pd.DataFrame(list(_SCHEMAS[function]), columns=["column", "dtype", "always", "meaning"])


def fixed_table(data: pd.DataFrame, columns: tuple[Column, ...], facets: list[str],
                hover: list[str]) -> pd.DataFrame:
    """data with every schema column, in schema order and type: facets, schema, hover."""
    out = pd.DataFrame(index=data.index)
    for name in facets:
        out[name] = data[name]
    for col in columns:
        if col.name in data:
            values = data[col.name]
        else:
            values = pd.Series([None] * len(data), index=data.index, dtype=object)
        if col.dtype in _PANDAS:
            values = values.astype(_PANDAS[col.dtype])
        elif col.dtype == "string":
            values = pd.Series([None if pd.isna(v) else str(v) for v in values],
                               index=data.index, dtype=object)
        out[col.name] = values
    for name in hover:
        out[name] = data[name]
    return out
