import json
import math
import pathlib
import pytest
import pandas as pd

from conformance_helpers import DISPATCH, extract

FIXTURES = sorted(pathlib.Path("fixtures").rglob("*.json"))

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
