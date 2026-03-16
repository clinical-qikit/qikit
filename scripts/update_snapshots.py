"""Regenerate snapshot fields in all fixture files."""
import json
import math
import pathlib
import sys
import numpy as np
import pandas as pd
from qikit import qic, paretochart, bchart, experiment

def experiment_analyze(factors, response, **kwargs):
    d = experiment.design(factors=factors, **kwargs)
    return d.fill(response)

DISPATCH = {
    "qic": qic, 
    "paretochart": paretochart, 
    "bchart": bchart,
    "experiment_design": lambda factors, **kwargs: experiment.design(factors=factors, **kwargs),
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

failures = []
paths = sorted(pathlib.Path("fixtures").rglob("*.json"))

if not paths:
    print("No fixtures found.")
    sys.exit(0)

for path in paths:
    print(f"Processing {path}...")
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

    # Gate: check must pass before snapshot updates
    for key, spec in fix["check"].items():
        actual = extract(result, key)
        if isinstance(spec, list):
            if not math.isclose(actual, spec[0], abs_tol=spec[1]):
                failures.append(f"{path.stem}.{key}: {actual} != {spec[0]}")
        elif actual != spec:
            failures.append(f"{path.stem}.{key}: {actual} != {spec}")

    if not failures:
        snapshot = result.to_dict()
        
        # Deep clean NaN to null for JSON compliance across languages
        def clean_nan(obj):
            if isinstance(obj, dict):
                return {k: clean_nan(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_nan(v) for v in obj]
            elif isinstance(obj, float) and math.isnan(obj):
                return None
            return obj
            
        fix["snapshot"] = clean_nan(snapshot)
        path.write_text(json.dumps(fix, indent=2, default=str) + "\n")

if failures:
    print("FAILED — snapshots not updated:")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)

print(f"Updated {len(paths)} snapshots.")
