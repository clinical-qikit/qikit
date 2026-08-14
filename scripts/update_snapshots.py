"""
Regenerate the snapshot field in all fixture files.

With --check, compare instead of write: recompute every snapshot and report any that
have gone stale, leaving the working tree untouched. That is the mode CI runs.

Why --check compares numerically rather than byte for byte. Snapshots hold computed
floats, and some of them come from math.lgamma, whose last ulp differs between
platforms — macOS/arm64 and linux/x86_64 disagree around the 14th significant digit,
and an iterative routine can turn that into a difference in the 11th. A byte
comparison therefore fails purely because the file was generated on a different
machine than the one checking it, which says nothing about staleness. The engine
change this gate exists to catch moves values by vastly more than SNAPSHOT_REL_TOL,
so a numeric comparison catches everything the byte comparison did and nothing else.
Structure, types, strings, booleans and null-vs-number are still compared exactly.
"""
import argparse
import json
import math
import pathlib
import sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tests"))
from conformance_helpers import DISPATCH, extract  # noqa: E402

# Four orders of magnitude below the tightest fixture check tolerance, and three
# above the platform noise it is there to absorb.
SNAPSHOT_REL_TOL = 1e-9
SNAPSHOT_ABS_TOL = 1e-12


def clean_nan(obj):
    """Deep clean NaN to null for JSON compliance across languages."""
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def snapshot_diffs(committed, fresh, path="snapshot", out=None):
    """
    Structural mismatches, and numeric ones beyond tolerance, as readable paths.

    Numbers compare with tolerance; everything else — including whether a value is
    null at all — compares exactly, so a NaN appearing or disappearing is still a
    hard failure.
    """
    out = [] if out is None else out

    if isinstance(committed, dict) and isinstance(fresh, dict):
        for key in sorted(set(committed) | set(fresh)):
            if key not in committed:
                out.append(f"{path}.{key}: missing from committed snapshot")
            elif key not in fresh:
                out.append(f"{path}.{key}: no longer produced by the engine")
            else:
                snapshot_diffs(committed[key], fresh[key], f"{path}.{key}", out)
    elif isinstance(committed, list) and isinstance(fresh, list):
        if len(committed) != len(fresh):
            out.append(f"{path}: length {len(committed)} != {len(fresh)}")
        else:
            for i, (c, f) in enumerate(zip(committed, fresh)):
                snapshot_diffs(c, f, f"{path}[{i}]", out)
    elif isinstance(committed, bool) or isinstance(fresh, bool):
        # bool before number: True == 1 would otherwise slip through.
        if committed is not fresh:
            out.append(f"{path}: {committed} != {fresh}")
    elif isinstance(committed, (int, float)) and isinstance(fresh, (int, float)):
        if not math.isclose(
            committed, fresh, rel_tol=SNAPSHOT_REL_TOL, abs_tol=SNAPSHOT_ABS_TOL
        ):
            out.append(f"{path}: {committed} != {fresh}")
    elif committed != fresh:
        out.append(f"{path}: {committed!r} != {fresh!r}")

    return out


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--check", action="store_true",
    help="Compare instead of writing; exit non-zero if any snapshot is stale.",
)
args = parser.parse_args()

failures = []
stale = []
paths = sorted(pathlib.Path("fixtures").rglob("*.json"))

if not paths:
    print("No fixtures found.")
    sys.exit(0)

for path in paths:
    if not args.check:
        print(f"Processing {path}...")
    fix = json.loads(path.read_text())
    fn = DISPATCH[fix["function"]]
    
    inputs = fix["input"].copy()
    if "data" in inputs and isinstance(inputs["data"], dict):
        inputs["data"] = pd.DataFrame(inputs["data"])
    
    if "clOverride" in inputs:
        inputs["cl"] = inputs.pop("clOverride")

    if "limitMethod" in inputs:
        inputs["limit_method"] = inputs.pop("limitMethod")

    # Strip TS-only keys before calling Python qic — it re-derives subgroup sizes
    # and the sigma estimate from the grouping column.
    inputs.pop("subgroupN", None)
    inputs.pop("sBar", None)
    inputs.pop("sigmaHat", None)
        
    result = fn(**inputs)

    # Gate: this file's check must pass before its snapshot is updated. Scoped
    # per-file so one bad fixture doesn't silently skip every fixture after it.
    file_failures = []
    for key, spec in fix["check"].items():
        actual = extract(result, key)
        if isinstance(spec, list):
            if not math.isclose(actual, spec[0], abs_tol=spec[1]):
                file_failures.append(f"{path.stem}.{key}: {actual} != {spec[0]}")
        elif actual != spec:
            file_failures.append(f"{path.stem}.{key}: {actual} != {spec}")

    if file_failures:
        failures.extend(file_failures)
        continue

    fresh = clean_nan(result.to_dict())

    if args.check:
        # json round-trip so the committed side is compared as it will be re-read,
        # not as live Python objects (tuples vs lists, numpy scalars, and so on).
        diffs = snapshot_diffs(fix.get("snapshot"), json.loads(json.dumps(fresh, default=str)))
        if diffs:
            stale.append((path, diffs))
        continue

    fix["snapshot"] = fresh
    path.write_text(json.dumps(fix, indent=2, default=str) + "\n")

if failures:
    print("FAILED — checks did not pass, snapshots not updated:")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)

if args.check:
    if stale:
        print("Committed snapshots do not match the engine output:\n")
        for path, diffs in stale:
            print(f"  {path}")
            for d in diffs[:8]:
                print(f"    {d}")
            if len(diffs) > 8:
                print(f"    ... and {len(diffs) - 8} more")
        print("\nRun 'uv run python scripts/update_snapshots.py' and commit the result.")
        sys.exit(1)
    print(f"All {len(paths)} snapshots current.")
else:
    print(f"Updated {len(paths)} snapshots.")
