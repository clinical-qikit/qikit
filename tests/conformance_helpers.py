"""Shared helpers for the fixture-conformance test and scripts/update_snapshots.py."""
import numpy as np
from qikit import qic, paretochart, bchart, design


def experiment_analyze(factors, response, **kwargs):
    d = design(factors=factors, **kwargs)
    return d.fill(response)


DISPATCH = {
    "qic": qic,
    "paretochart": paretochart,
    "bchart": bchart,
    "experiment_design": lambda factors, **kwargs: design(factors=factors, **kwargs),
    "experiment_analyze": experiment_analyze,
}


def extract(result, key):
    """Pull a check value from a result object."""
    if key == "signals":
        return bool(result.signals)

    # Check if it's a column in result.data
    if hasattr(result, "data") and key in result.data.columns:
        val = result.data[key].iloc[0]
        if isinstance(val, (np.floating, float)):
            return float(val)
        if isinstance(val, (np.integer, int)):
            return int(val)
        if isinstance(val, (np.bool_, bool)):
            return bool(val)
        return val

    # Check if it's an attribute
    if hasattr(result, key):
        val = getattr(result, key)
        if isinstance(val, (np.floating, float)):
            return float(val)
        return val

    # Check if it's in summary
    if hasattr(result, "summary") and key in result.summary:
        val = result.summary.get(key)
        if isinstance(val, (np.floating, float)):
            return float(val)
        return val

    raise KeyError(f"Key {key!r} not found in result {type(result)}")
