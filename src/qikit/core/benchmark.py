"""
benchmark.py — a goal the best providers already reach (docs/methods.md §4.18).

    abc()   Kiefe and Weissman's achievable benchmark of care, and whom it pools
    msd()   the minimum sufficient denominator: below it, a perfect score can be luck
"""

from __future__ import annotations

import math

import numpy as np

# A provider holding fewer cases than the minimum sufficient denominator could reach
# 100% by chance at this one-sided level (Kiefe 1998, Table 3).
MSD_ALPHA = 0.025


def abc(num: np.ndarray, den: np.ndarray, n_model: np.ndarray, cl: float,
        eligible: np.ndarray, share: float, *, proportion: bool,
        lower_is_worse: bool) -> tuple[float, np.ndarray]:
    """
    Kiefe's achievable benchmark of care: (ABC, which providers it pools).

    The eligible providers are ranked best first by an adjusted rate that keeps one with
    few cases from topping the list on luck, taken in that order until they hold the
    share of the eligible denominator, together with every provider tied with the one
    that reaches it (Weissman et al. 1999). The ABC is their pooled raw rate Σy/Σn.

    On a proportion the adjusted rate is Kiefe's (y + 1)/(n + 2), a Beta(1, 1) prior. On
    a count it adds one event at the center line instead, an extension its authors would
    caution against.
    """
    group = np.zeros(len(num), dtype=bool)
    if not eligible.any():
        return math.nan, group
    # Counts on the scale the model sees (y/φ out of n/φ under within_dispersion).
    with np.errstate(divide="ignore", invalid="ignore"):
        y_eff = np.where(den > 0, num * n_model / den, np.nan)
    if proportion:
        adjusted = (y_eff + 1.0) / (n_model + 2.0)
    else:
        prior_n = 1.0 / cl if cl > 0 else math.inf
        adjusted = (y_eff + 1.0) / (n_model + prior_n)
    rank = -adjusted if lower_is_worse else adjusted        # ascending: best first
    idx = np.flatnonzero(eligible)
    idx = idx[np.argsort(rank[idx], kind="stable")]
    reached = np.cumsum(den[idx]) >= share * float(den[idx].sum()) * (1 - 1e-12)
    breakpoint = rank[idx[int(np.argmax(reached))]]
    # Everyone tied at the breakpoint joins, so the share held can run past the target.
    chosen = idx[rank[idx] <= breakpoint + 1e-12 * abs(breakpoint)]
    group[chosen] = True
    return float(num[chosen].sum() / den[chosen].sum()), group


def msd(cl: float, *, proportion: bool, worse: str | None) -> float:
    """
    The minimum sufficient denominator: the fewest cases at which perfect performance
    would be a one-sided 2.5% event if the provider's true rate were the center line.
    On a proportion, the smallest N with p̄ᴺ < 0.025, p̄ the rate in the good direction;
    it reproduces every row of Kiefe et al.'s Table 3. On a count with worse="higher",
    the exposure at which zero events has probability e^(−θ₀n) < 0.025.
    """
    if proportion:
        good = cl if worse == "lower" else 1.0 - cl
        if good <= 0:
            return 1.0
        if good >= 1:
            return math.inf
        return float(math.floor(math.log(MSD_ALPHA) / math.log(good)) + 1)
    if worse == "higher" and cl > 0:
        return -math.log(MSD_ALPHA) / cl
    return math.inf
