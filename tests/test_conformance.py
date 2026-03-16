import json
import math
import pathlib
import pytest
import numpy as np
import pandas as pd
from qikit import qic, paretochart, bchart, design, analyze

def experiment_analyze(factors, response, **kwargs):
    d = design(factors=factors, **kwargs)
    return d.fill(response)

FIXTURES = sorted(pathlib.Path("fixtures").rglob("*.json"))
DISPATCH = {
    "qic": qic, 
    "paretochart": paretochart, 
    "bchart": bchart,
    "experiment_design": lambda factors, **kwargs: design(factors=factors, **kwargs),
    "experiment_analyze": experiment_analyze
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

@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture(path):
    fix = json.loads(path.read_text())
    fn = DISPATCH[fix["function"]]
    
    inputs = fix["input"].copy()
    if "data" in inputs and isinstance(inputs["data"], dict):
        inputs["data"] = pd.DataFrame(inputs["data"])
    
    if "clOverride" in inputs:
        inputs["cl"] = inputs.pop("clOverride")
    
    # Strip TS-only keys before calling Python qic
    inputs.pop("subgroupN", None)
    inputs.pop("sBar", None)
        
    result = fn(**inputs)

    for key, spec in fix["check"].items():
        actual = extract(result, key)
        if isinstance(spec, list):  # [value, tolerance]
            assert math.isclose(actual, spec[0], abs_tol=spec[1]), \
                f"{key}: {actual} != {spec[0]} (±{spec[1]})"
        else:
            assert actual == spec, f"{key}: {actual} != {spec}"
