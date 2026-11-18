"""
_funnel/summary.py — a facet's summary: the fixed-center gap guard, benchmarks,
expected false flags, dispersion shape, power, and the notes a reader sees.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..core.benchmark import abc, msd
from ..core.dispersion import (
    center_gap_p_value,
    dispersion_shape,
    natural_tau2,
    overdispersion,
    pooled,
    tau2_ml,
)
from ..core.power import UNDERPOWERED_RATIO
from ..core.pvalues import signal_thresholds
from ..validate import warn
from ..within import Within
from .settings import _Fit, _Settings

_QUESTION = {
    "peers": "This chart asks whether each provider is unusual among its peers: the center "
             "line is their pooled value, and the limits allow for the spread between them.",
    "model": "This chart asks whether each provider differs from the risk model: the center "
             "line is 1.0 (observed equals expected), with no allowance for spread between "
             "providers.",
}

# The fixed-center gap guard (methods §4.2.1): warn when the providers' pooled value
# differs from a center= the caller fixed, under overdispersion=True, by enough that τ̂
# absorbs it. Both conditions must hold: the gap is beyond chance and the spread between
# providers (p below _GAP_MAX_P, a sandwich-variance t test), and it widens the limits at
# the median provider's volume by at least _GAP_MIN_WIDEN. scripts/simulate_center_gap.py
# calibrates both: at most 0.4% false warnings in any cell (K 20-1000, tau 0-0.2,
# phi 1-2), and 51-99% warned at a 10% gap on hospital volumes.
_GAP_MAX_P = 0.001
_GAP_MIN_WIDEN = 1.10


def _center_gap(st: _Settings, fit: _Fit, source: str, tau_scale: str, notes) -> dict:
    """
    center_gap, center_gap_p, tau_pooled; and the warning when a fixed center line under
    overdispersion=True has τ̂ absorbing a system-wide gap (methods §4.2.1). tau_scale is
    the scale tau_method estimates on, whether or not this period found any spread.
    """
    out: dict[str, Any] = {"center_gap": None, "center_gap_p": None, "tau_pooled": None}
    if not (st.center_user_fixed and st.overdispersion and source == "estimated"):
        return out
    cl, ratio, n_model, family = fit.cl, fit.ratio, fit.n_model, fit.family
    ok = fit.mask & np.isfinite(ratio) & (n_model > 0)
    if ok.sum() < 2:
        return out
    center = pooled(ratio, n_model, ok)
    if st.tau_method == "ml":
        tau2_p, _ = tau2_ml(center, ratio, n_model, ok, family)
    else:
        tau2_p = overdispersion(st.tau_method, family, center, ratio, n_model, ok).tau2
    nat_fixed = natural_tau2(tau_scale, cl, fit.tau2)
    nat_pooled = natural_tau2(tau_scale, center, tau2_p)
    binomial = family == "binomial"

    def var(theta):
        return theta * (1.0 - theta) if binomial else theta

    p = center_gap_p_value(center, cl, ratio[ok], n_model[ok])
    v_med = var(cl) / float(np.median(n_model[ok]))
    widen = math.sqrt((v_med + nat_fixed) / (v_med + nat_pooled))
    gap = center / cl - 1.0
    out.update({"center_gap": gap, "center_gap_p": p, "tau_pooled": math.sqrt(tau2_p)})
    if p < _GAP_MAX_P and widen >= _GAP_MIN_WIDEN:
        fix = ("for 'worse than the risk model?' use compare_to='model'"
               if st.measure == "oe" else
               f"for 'different from the target?' pass overdispersion=False with "
               f"center={cl:g}")
        note = (f"The spread between providers is absorbing a {gap:+.0%} system-wide gap "
                f"between the providers' pooled value ({center:.3g}) and center={cl:g}, "
                f"which widens every limit (by about {widen - 1:.0%} at the median "
                f"volume). For 'unusual among peers?' leave center unset; {fix}.")
        notes.append(note)
        warn(note)
    return out


def _add_benchmark(table, summary, notes, st: _Settings, fit: _Fit, num, den,
                   excluded) -> None:
    """The benchmark= columns, summary keys and notes for one facet (methods §4.18)."""
    m, share = st.multiply, st.benchmark_share
    cl, ratio, n_model = fit.cl, fit.ratio, fit.n_model
    how = dict(proportion=st.measure == "proportion", lower_is_worse=st.worse == "lower")
    eligible = ~excluded & np.isfinite(num) & (den > 0)
    if st.benchmark == "eb":
        eb = table["eb_rate"].to_numpy(dtype=float) / m
        q = 1.0 - share if st.worse == "lower" else share
        value = float(np.quantile(eb[eligible], q)) if eligible.any() else math.nan
        bench = {"method": "eb", "share": share, "value": value * m}
        if not (table["reliability"].to_numpy(dtype=float) > 0).any():
            notes.append("The funnel finds no spread between providers, so every shrunk "
                         "estimate equals the center line and so does the benchmark.")
    else:
        value, group = abc(num, den, n_model, cl, eligible, share, **how)
        floor = msd(cl, proportion=st.measure == "proportion", worse=st.worse)
        small = eligible & (n_model < floor)
        without, _ = abc(num, den, n_model, cl, eligible & ~small, share, **how)
        held = den[group]
        table["benchmark_group"] = group
        bench = {
            "method": "abc", "share": share, "value": value * m,
            "providers": int(group.sum()),
            "coverage": float(held.sum() / den[eligible].sum()) if group.any() else 0.0,
            "group_denominator": (
                {"median": float(np.median(held)), "min": float(held.min()),
                 "max": float(held.max())} if group.any() else None),
            "msd": floor if math.isfinite(floor) else None,
            "n_below_msd": int(small.sum()),
            "without_small": without * m,
        }
        if st.measure != "proportion":
            notes.append(
                "The achievable benchmark was designed for process-of-care proportions; its "
                "authors urge that it be applied to outcome measures with extreme caution, if "
                "at all. benchmark=\"eb\" is the outcome alternative."
            )
        if 0 < group.sum() < 3:
            notes.append(
                f"The achievable benchmark rests on {int(group.sum())} provider(s): one or "
                f"two high-volume providers hold {share:.0%} of the denominator, so treat it "
                "as provisional."
            )
        if small.any() and math.isfinite(without) and abs(without - value) > 0.05 * abs(value):
            notes.append(
                f"Without the {int(small.sum())} providers below the minimum sufficient "
                f"denominator ({floor:.3g}) the achievable benchmark would be "
                f"{_two_sig(without * m)} rather than {_two_sig(value * m)}: it leans on "
                "low-volume providers."
            )
    summary["benchmark"] = bench
    table["benchmark"] = np.full(len(table), bench["value"])
    with np.errstate(invalid="ignore"):
        meets = ratio >= value if st.worse == "lower" else ratio <= value
    table["meets_benchmark"] = meets & np.isfinite(ratio)


def _expected_false_flags(st: _Settings, s: dict) -> dict[str, float]:
    """
    How many of the flags chance alone would explain. Under "limits": K·α per tier, the
    count a chart of K average providers would put there. Under "fdr": the false
    discovery bound, at most q₀ of the outliers and q₁ of outliers and alerts together.
    """
    if st.signal == "limits":
        outer, inner = signal_thresholds(st.side, st.limits)
        k = s["n_tested"]
        return {"outlier": round(k * outer, 2), "alert": round(k * (inner - outer), 2)}
    q0, q1 = st.fdr_levels
    return {"outlier": round(q0 * s["n_outlier"], 2),
            "outlier_or_alert": round(q1 * (s["n_outlier"] + s["n_alert"]), 2)}


# The case-level clustering check (within_check = (φ̂, p) from case rows) warns when the
# rows are clearly more variable than independent cases. The floor matters more than the
# test, which is very powerful on N − K degrees of freedom: at φ = 1.25 the 99.8% limits
# are √1.25 too narrow (docs/methods.md §4.13, §5).
_ROWS_MIN_PHI = 1.25
_ROWS_MAX_P = 0.001


def _shape(fit: _Fit, within: Within, measure, notes) -> dict:
    """dispersion_shape, its φ hint, and the clustered-counts warning (methods §4.12)."""
    out = dispersion_shape(fit.cl, fit.ratio, fit.n_model, fit.mask, fit.family)
    if "within_dispersion_hint" in out:
        out["within_dispersion_hint_source"] = "totals"
    check = within.check
    if check is not None and check[0] >= _ROWS_MIN_PHI and check[1] < _ROWS_MAX_P:
        shape = out.get("dispersion_shape")
        out["dispersion_shape"] = "both" if shape in ("between", "both") else "within"
        out["within_dispersion_hint"] = round(float(check[0]), 2)
        out["within_dispersion_hint_source"] = "rows"
    if out.get("dispersion_shape") in ("within", "both") and within.source == "default":
        hint = out["within_dispersion_hint"]
        if measure == "proportion":
            example = "the questions of one survey, which one patient answers alike"
            fix = ("Pass one row per case (per survey: y = items meeting the measure, n = "
                   "items answered) with within_dispersion='estimate', or a known "
                   f"within_dispersion= (the spread here suggests about {hint:.1f}).")
        else:
            example = "patient-days, where one stay adds many days"
            fix = ("Pass stay-level rows (one per case) with within_dispersion='estimate', "
                   f"or a known within_dispersion= (the spread here suggests about {hint:.1f}).")
        note = (f"Counts look clustered within providers (e.g. {example}): the spread is "
                f"about {hint:.1f} times what the count model allows at every volume, so "
                f"small providers are over-flagged and p- and q-values are too small. {fix}")
        notes.append(note)
        warn(note)
    if within.source == "estimated" and within.phi < 1.0 and measure != "mean":
        notes.append(
            f"within_dispersion was estimated at {within.phi:.2f}, below 1: single cases vary "
            f"less than a Poisson count, as binary outcomes do (the variance, the sum of "
            f"p(1 - p), is below E). The limits use it, which narrows them; pass within_dispersion=1 to keep "
            f"the Poisson model."
        )
    return out


def _power(measure: str, det, cl, excluded, notes) -> dict:
    """
    Whether the typical provider could detect a doubling (methods §4.8). On O/E the test
    is min_detectable > 2; on a proportion or rate, min_detectable / cl > 2, with points
    that cannot flag at all counted as underpowered.
    """
    counted = det[~excluded]
    if measure == "oe":
        finite = counted[np.isfinite(counted)]
        if len(finite) == 0:
            return {}
        median = float(np.median(finite))
        n_under = int(np.sum(finite > UNDERPOWERED_RATIO))
        out = {"min_detectable_median": median, "n_underpowered": n_under,
               "underpowered": median > UNDERPOWERED_RATIO}
        if out["underpowered"]:
            notes.append(
                f"{n_under} of {len(finite)} points have too few expected events to detect "
                f"even a doubling of risk (smallest detectable O/E, median: {median:.1f}). "
                f"Absence of a signal is not evidence of acceptable performance; aggregate "
                f"more time periods or compare at a higher level before drawing conclusions."
            )
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = counted / (cl if cl > 0 else np.nan)
    ratio = ratio[~np.isnan(ratio)]
    if len(ratio) == 0:
        return {}
    median = float(np.median(ratio))
    n_under = int(np.sum(ratio > UNDERPOWERED_RATIO))
    out = {"min_detectable_median": median if math.isfinite(median) else math.nan,
           "n_underpowered": n_under, "underpowered": median > UNDERPOWERED_RATIO}
    if out["underpowered"]:
        noun = {"proportion": "proportion", "mean": "mean"}.get(measure, "rate")
        reach = (f"median: {median:.1f}× the center line" if math.isfinite(median)
                 else "median: none, most points cannot flag at all")
        notes.append(
            f"{n_under} of {len(ratio)} points have too few cases to detect even a "
            f"doubling of the center-line {noun} (smallest detectable {noun}, {reach}). "
            f"Absence of a signal is not evidence of acceptable performance; aggregate "
            f"more time periods or compare at a higher level before drawing conclusions."
        )
    return out


_SPREAD = {"oe": ("the risk model and chance", "O/E"), "proportion": ("chance", "proportions"),
           "rate": ("chance", "rates"), "mean": ("chance", "means")}


def _notes(s: dict, st: _Settings, notes: list[str]) -> None:
    """The reader-facing sentences, in order of how much they change the reading."""
    if not st.overdispersion and s["tau_estimated"] > 0:
        basis, quantity = _SPREAD[st.measure]
        notes.append(
            f"Providers vary more than {basis} can explain: the estimated spread of true "
            f"{quantity} between them is tau = {_two_sig(s['tau_estimated'])}. Some signals "
            f"here may reflect that spread (unmeasured case mix, data differences, or real "
            f"variation in practice) rather than an individually unusual provider. Compare "
            f"with overdispersion=True, which judges each provider against that spread, and "
            f"look for its cause: an adjustment is a temporary measure, not a fix."
        )
    if s["n_fragile"]:
        note = (f"{s['n_fragile']} flagged provider(s) stop flagging when their single most "
                f"extreme case is removed (fragility = 1): review that case before acting.")
        if st.measure != "proportion" and s["within_dispersion"] == 1.0:
            note += (" On event counts every event is one patient, so at low volume this is "
                     "expected and is not by itself a data problem.")
        notes.append(note)
    k = s["n_tested"]
    if st.overdispersion and s["tau_source"] == "estimated" and 0 < k < 30:
        notes.append(
            f"With {k} providers the spread between them (tau = {s['tau']:.3g}) is "
            f"imprecise. Consider a pre-specified tau= estimated from earlier periods."
        )
    est, fixed = s["tau_estimated"], s["tau"]
    if (st.overdispersion and s["tau_source"] == "pre-specified" and fixed
            and not (fixed / 1.5 <= est <= fixed * 1.5)):
        notes.append(
            f"The pre-specified tau = {fixed:.3g} differs from this period's estimate, "
            f"{est:.3g}, by more than 1.5-fold: the spread between providers may have "
            f"changed since tau was set. Review it before relying on these limits."
        )
    if s["n_filtered"]:
        notes.append(
            f"{s['n_filtered']} provider(s) below fdr_min_denominator = {st.fdr_min:g} were "
            f"left out of the false discovery rate step: they keep a p-value but have no "
            f"q-value."
        )


def _two_sig(x: float) -> str:
    """x to two significant figures in fixed notation."""
    if not (x > 0) or not math.isfinite(x):
        return f"{x:.2f}"
    return f"{x:.{max(0, 1 - math.floor(math.log10(x)))}f}"
