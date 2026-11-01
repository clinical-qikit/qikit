"""
qikit against the R packages it claims to follow, on public data.

The fixtures in fixtures/reference/ are written by scripts/make_reference_fixtures.R
(qicharts2, FunnelPlotR, NHSRplotthedots). Every comparison here is exact to 1e-6 unless
it is listed in DEPARTURES with its reason; docs/qic-methods.md and docs/methods.md
record the same list for readers.
"""

from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd
import pytest

from qikit import funnel, qic

REF = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "reference"
RTOL = 1e-6


def _load(prefix: str) -> list[pathlib.Path]:
    return sorted(REF.glob(f"{prefix}*.json"))


def _close(actual, expected, what: str) -> None:
    a = np.asarray(actual, dtype=float)
    e = np.array([np.nan if v is None else v for v in expected], dtype=float)
    assert a.shape == e.shape, f"{what}: {a.shape} != {e.shape}"
    both_nan = np.isnan(a) & np.isnan(e)
    ok = both_nan | np.isclose(a, e, rtol=RTOL, atol=1e-9)
    bad = np.flatnonzero(~ok)
    assert not len(bad), f"{what}: first mismatch at {bad[0]}: {a[bad[0]]} != {e[bad[0]]}"


# ---------------------------------------------------------------------------
# qicharts2
# ---------------------------------------------------------------------------

# Where qikit deliberately differs from qicharts2: {fixture: {column: reason}}. Each is
# recorded in docs/qic-methods.md.
DEPARTURES = {
    "qicharts2_mr_cdi": {
        "ucl_95": "the 2σ line of a moving range is MR̄(1 + 2·d3/d2) = 2.511·MR̄; "
                  "qicharts2 draws 2/3 of the UCL (2.178·MR̄)",
    },
    "qicharts2_s_cabg": {
        col: "unequal subgroups: CLᵢ = c4(nᵢ)·σ̂ with σ̂ = Sp/c4(d + 1), so the centre "
             "follows E[sᵢ]; qicharts2 keeps a flat CL = Sp with B3/B4(nᵢ)"
        for col in ("cl", "ucl", "lcl", "ucl_95", "lcl_95", "signal", "runs")
    },
    "qicharts2_xbar_cabg": {
        col: "unequal subgroups: ±3σ̂/√nᵢ with the unbiased σ̂ = Sp/c4(d + 1); qicharts2 "
             "uses A3(nᵢ)·Sp, which corrects with c4(nᵢ) instead (a fraction of a percent)"
        for col in ("ucl", "lcl", "ucl_95", "lcl_95", "signal")
    },
}


def _qic_from_fixture(inp: dict):
    """The fixture's call, in qikit's terms. part and freeze both mean 'after point k'."""
    frame = pd.DataFrame({k: inp[k] for k in ("x", "y", "n") if k in inp})
    if pd.api.types.is_string_dtype(frame["x"]):
        # R wrote its Date x as ISO text; qicharts2 treats a date as ordered, text as not.
        frame["x"] = pd.to_datetime(frame["x"])
    kw = {k: inp[k] for k in ("freeze", "part", "multiply") if k in inp}
    return qic(frame, x="x", y="y", n="n" if "n" in inp else None, chart=inp["chart"], **kw)


@pytest.mark.parametrize("path", _load("qicharts2_"), ids=lambda p: p.stem)
def test_qicharts2(path):
    fix = json.loads(path.read_text())
    exp = fix["expected"]
    r = _qic_from_fixture(fix["input"])
    d = r.data
    skip = DEPARTURES.get(path.stem, {})
    columns = ["y", "cl", "ucl", "lcl"]
    if fix["input"]["chart"] != "run":
        columns += ["ucl_95", "lcl_95"]
    for col in columns:
        if col not in skip:
            _close(d[col], exp[col], col)
    if "signal" not in skip:
        np.testing.assert_array_equal(
            d["signal"].to_numpy() == "outlier", np.asarray(exp["sigma_signal"], dtype=bool),
            err_msg="points beyond the limits",
        )
    parts = r.summary.get("parts") or [r.summary]
    if "runs" in skip:
        return
    for got, want in zip(parts, exp["runs"].values()):
        for key in ("n_useful", "longest_run", "longest_run_max", "n_crossings",
                    "n_crossings_min", "runs_signal"):
            assert got[key] == want[key], f"{key}: {got[key]} != {want[key]}"


# ---------------------------------------------------------------------------
# FunnelPlotR
# ---------------------------------------------------------------------------

_MEASURE = {"SR": "oe", "PR": "proportion"}
_METHOD = {("SR", "SHMI"): "shmi", ("SR", "CQC"): "cqc", ("PR", "SHMI"): "cqc"}


@pytest.mark.parametrize("path", _load("funnelplotr_"), ids=lambda p: p.stem)
# Length of stay as O/E days is clustered within stays, and qikit says so; the reference
# reproduces FunnelPlotR's numbers on that data all the same.
@pytest.mark.filterwarnings("ignore:Counts look clustered")
def test_funnelplotr(path):
    fix = json.loads(path.read_text())
    inp, exp = fix["input"], fix["expected"]
    frame = pd.DataFrame({"unit": inp["unit"], "y": inp["y"], "n": inp["n"]})
    r = funnel(
        frame, y="y", n="n", unit="unit", measure=_MEASURE[inp["data_type"]],
        tau_method=_METHOD[(inp["data_type"], inp["sr_method"])],
        # FunnelPlotR benchmarks a standardised ratio against 1, a proportion against
        # the pooled rate.
        center=1.0 if inp["data_type"] == "SR" else None,
    )
    s = r.summary
    assert s["phi"] == pytest.approx(exp["phi"], rel=RTOL)
    assert s["tau"] ** 2 == pytest.approx(exp["tau2"], rel=RTOL, abs=1e-12)
    d = r.data.set_index("unit").loc[inp["unit"]]
    if exp["tau2"] > 0 and fix["input"]["sr_method"] != "CQC":
        # Departure: FunnelPlotR draws CQC limits as 1 ± z·√(s² + τ²) on the square-root
        # scale without squaring back, so they are about half the correct width. qikit
        # squares them back (docs/methods.md §4.17); phi and tau2 still match.
        # Departure: where the arcsine contour passes 100% (sin² beyond π/2), FunnelPlotR's
        # limit folds back below 1; qikit caps it at 1, the largest proportion possible.
        capped = d["upper_alert"].to_numpy() >= 1.0
        _close(d["lower_outlier"], exp["od99_lcl"], "od99_lcl")
        _close(d["upper_outlier"], exp["od99_ucl"], "od99_ucl")
        _close(d["lower_alert"], exp["od95_lcl"], "od95_lcl")
        _close(d["upper_alert"][~capped], np.asarray(exp["od95_ucl"], dtype=object)[~capped],
               "od95_ucl")
        flagged = d["signal"].to_numpy() == "outlier"
        np.testing.assert_array_equal(flagged, np.asarray(exp["outlier"], dtype=bool))


# ---------------------------------------------------------------------------
# NHSRplotthedots (NHS England Making Data Count)
# ---------------------------------------------------------------------------

_POINT = {"special_cause_improvement": "improving", "special_cause_concern": "concerning",
          "special_cause_neutral_high": "neutral", "special_cause_neutral_low": "neutral",
          "common_cause": "common"}
_ASSURANCE = {"consistent_pass": "pass", "consistent_fail": "fail",
              "inconsistent": "variable"}


@pytest.mark.parametrize("path", _load("nhsrplotthedots_"), ids=lambda p: p.stem)
def test_nhsrplotthedots(path):
    fix = json.loads(path.read_text())
    inp, exp = fix["input"], fix["expected"]
    frame = pd.DataFrame({"x": pd.to_datetime(inp["x"]), "y": inp["y"]})
    kw = {k: inp[k] for k in ("freeze", "part", "target") if inp.get(k) is not None}
    # Making Data Count names the good direction ("improvement"); qikit names the bad one.
    r = qic(frame, x="x", y="y", chart="i", method="nhs",
            worse="lower" if inp["improvement"] == "increase" else "higher", **kw)
    d = r.data
    for col in ("cl", "ucl", "lcl"):
        _close(d[col], exp[col], col)
    np.testing.assert_array_equal(
        d["variation"].to_numpy(), np.array([_POINT[t] for t in exp["point_type"]]),
    )
    if exp.get("assurance_type") is not None:
        assert r.summary["assurance"] == _ASSURANCE[exp["assurance_type"]]
