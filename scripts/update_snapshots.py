"""Regenerate snapshot fields in all fixture files."""
import json
import math
import pathlib
import sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tests"))
from conformance_helpers import DISPATCH, extract  # noqa: E402

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
