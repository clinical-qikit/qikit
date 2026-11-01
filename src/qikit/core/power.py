"""
power.py — what each provider could have shown: detectability and its own interval.

At physician volumes a funnel mostly cannot detect even a doubling of risk, and a blank
funnel reads as a clean bill of health. Every funnel therefore reports, per provider, the
smallest true value it had an 80% chance of flagging against the line actually drawn, and
an exact 95% interval for its own value (methods §4.8): Garwood for counts [5],
Clopper–Pearson for proportions [14], Korn–Graubard's effective-sample-size version at a
fractional denominator [16].

[5]  Garwood F. Fiducial limits for the Poisson distribution. Biometrika 1936;28:437-442.
[14] Clopper CJ, Pearson ES. The use of confidence or fiducial limits illustrated in the
     case of the binomial. Biometrika 1934;26(4):404-413.
[16] Korn EL, Graubard BI. Surv Methodol 1998;24(2):193-201.
"""

from __future__ import annotations

import math

import numpy as np

from .constants import Z_80, Z_95
from .contours import _integer_count, fractional_binomial_tails
from .dist import (
    _MEAN_SOLVE_MAX_K,
    binomial_cdf,
    brent,
    binomial_theta_for_cdf,
    poisson_mean_for_cdf,
)

# Power is fixed at 80% and the reference effect at a doubling; neither is a parameter,
# because on a chart that feeds credentialing a tunable threshold invites reporting
# whichever number reads best (methods §4.8).
UNDERPOWERED_RATIO = 2.0


def point_power(
    family: str, y: np.ndarray, n: np.ndarray, ucl: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    (detectable, ci_lower, ci_upper) per point, on the raw y scale. y is the ratio,
    proportion or rate, n the denominator the model sees (n/φ under within_dispersion),
    ucl the drawn upper contour. detectable is inf where no count could flag.
    """
    k = len(y)
    det, lo, hi = np.full(k, np.nan), np.full(k, np.nan), np.full(k, np.nan)
    for i in range(k):
        ni = float(n[i])
        t, x = float(ucl[i]) * ni, float(y[i]) * ni
        if family == "binomial":
            det[i] = binomial_detectable_rate(t, ni)
            lo[i], hi[i] = binomial_point_ci(x, ni)
        else:
            det[i] = oe_detectable_ratio(t, ni)
            lo[i], hi[i] = oe_point_ci(x, ni)
    return det, lo, hi


def oe_detectable_ratio(t_count: float, e: float) -> float:
    """
    Smallest true O/E this point has an 80% chance of flagging.

    A funnel at physician volumes is mostly a test with no power. A physician with
    5 expected deaths who is genuinely twice as deadly as predicted is flagged about
    a fifth of the time; the other four fifths the chart says nothing and a reader
    concludes the performance was acceptable. This function makes that limit visible
    per point, so "no signal" can be read against what a signal would have required.

    t_count is the drawn upper limit on the *count* scale (ucl · E). _sigma_signals
    flags strictly y > ucl, so an integer count flags iff O ≥ floor(t_count) + 1, and
    the power at true ratio ρ is P(X > floor(t_count); ρE). Setting that to 0.8 and
    inverting the CDF in its mean gives the answer exactly — no search over ratios.

    80% is the conventional power target and is deliberately not a parameter: on a
    chart that feeds credentialing, a tunable detectability threshold is an invitation
    to report whichever number reads best.

    Returns NaN when the point has no usable expected count.
    """
    if not (e > 0) or math.isnan(e) or math.isnan(t_count) or math.isinf(t_count):
        return math.nan

    m = math.floor(t_count)
    if m < 0:
        return math.nan

    if m <= _MEAN_SOLVE_MAX_K:
        lam_star = poisson_mean_for_cdf(int(m), 0.2)
    else:
        # Normal approximation with a continuity correction, solving
        # λ − Z_80·√λ = m + 0.5 as a quadratic in √λ. Only reachable at counts where
        # the two agree to ~1e-5 relative, and where power is ~1 for any ratio a
        # reader would care about.
        s = (Z_80 + math.sqrt(Z_80 * Z_80 + 4.0 * (m + 0.5))) / 2.0
        lam_star = s * s

    return lam_star / e


def oe_point_ci(o: float, e: float) -> tuple[float, float]:
    """
    Exact (Garwood) 95% confidence interval for this point's own O/E ratio.

    Distinct from the funnel band, and the distinction matters: the band answers
    "where would this point fall if the risk model were right and this provider were
    average", while this interval answers "given what this provider actually did, what
    range of true O/E is consistent with it". The band is a property of the null; the
    interval is a property of the point, and does not move when θ₀ does.

    Garwood's construction inverts the exact Poisson test: the lower bound is the mean
    at which observing this many events or more has probability 0.025, the upper bound
    the mean at which observing this many or fewer has probability 0.025. Zero observed
    events gives a lower bound of exactly 0 and an upper bound of −ln(0.025)/E.

    Falls back to Byar's closed form when the count is not an integer (an aggregate
    that has been averaged rather than summed) or is large enough that the bisection
    stops being worth its cost; both are outside the small-count regime where exactness
    is the whole point.
    """
    if not (e > 0) or math.isnan(e) or math.isnan(o) or o < 0:
        return (math.nan, math.nan)

    o_r = round(o)
    integral = abs(o - o_r) <= 1e-9 * max(1.0, abs(o))

    if integral and o_r <= _MEAN_SOLVE_MAX_K:
        mu_lower = 0.0 if o_r == 0 else poisson_mean_for_cdf(int(o_r) - 1, 0.975)
        mu_upper = poisson_mean_for_cdf(int(o_r), 0.025)
    else:
        mu_lower = (
            0.0 if o <= 0
            else o * max(0.0, 1.0 - 1.0 / (9.0 * o) - Z_95 / (3.0 * math.sqrt(o))) ** 3
        )
        mu_upper = (o + 1.0) * (
            1.0 - 1.0 / (9.0 * (o + 1.0)) + Z_95 / (3.0 * math.sqrt(o + 1.0))
        ) ** 3

    return (mu_lower / e, mu_upper / e)


def binomial_detectable_rate(t_count: float, n: float) -> float:
    """
    Smallest true proportion this point has an 80% chance of flagging on a p funnel.

    The binomial twin of oe_detectable_ratio, and exact in the same way: an integer
    count flags iff X ≥ floor(t_count) + 1, so the answer is the θ at which
    F(floor(t_count); n, θ) = 0.2, found by inverting the CDF in θ. A u funnel needs
    no twin: its counts are Poisson, and oe_detectable_ratio(ucl·n, n) is already the
    detectable rate.

    Returns inf when no count can flag at all — the upper limit sits at or above n,
    which happens at a handful of cases against a high center line — and NaN when the
    point has no usable denominator. A non-integer n (ν = n/φ under within_dispersion)
    interpolates the chance of flagging in ν between its whole neighbours, as the
    limits do (§4.13).
    """
    if not (n > 0) or math.isnan(t_count) or math.isinf(t_count):
        return math.nan
    m = _integer_count(n)
    if m is None:
        return _fractional_detectable_rate(t_count / n, n)
    thr = math.floor(t_count)
    if thr < 0:
        return math.nan
    if thr >= m:
        return math.inf
    return binomial_theta_for_cdf(int(thr), m, 0.2)


def binomial_point_ci(x: float, n: float) -> tuple[float, float]:
    """
    Exact (Clopper–Pearson) 95% confidence interval for this point's own proportion.

    The binomial counterpart of oe_point_ci's Garwood interval, and the same
    construction: the lower bound is the θ at which x or more events has probability
    0.025, the upper the θ at which x or fewer does. x = 0 gives a lower bound of
    exactly 0 and x = n an upper bound of exactly 1. A non-integer count or
    denominator (an effective count under within_dispersion) takes the same
    construction on the interpolated tails (_fractional_point_ci).
    """
    if not (n > 0) or math.isnan(x) or x < 0 or x > n:
        return (math.nan, math.nan)
    m = _integer_count(n)
    k = _integer_count(x)
    if m is None or k is None:
        return _fractional_point_ci(x, n)
    lo = 0.0 if k == 0 else binomial_theta_for_cdf(k - 1, m, 0.975)
    hi = 1.0 if k == m else binomial_theta_for_cdf(k, m, 0.025)
    return (lo, hi)


def _fractional_detectable_rate(ucl: float, nu: float) -> float:
    """
    binomial_detectable_rate at a fractional ν: the θ at which the chance of landing
    beyond the drawn upper contour ucl, interpolated in ν between m₀ and m₁ as the
    tails are, is 80%. inf when it never reaches 80%.
    """
    m0 = int(math.floor(nu))
    w = nu - m0
    thr0 = math.floor(ucl * m0)
    thr1 = math.floor(ucl * (m0 + 1))

    def miss(theta):
        return (1.0 - w) * binomial_cdf(thr0, m0, theta, cache=False) + w * binomial_cdf(thr1, m0 + 1, theta, cache=False)

    if miss(1.0) > 0.2:
        return math.inf
    return brent(lambda t: miss(t) - 0.2, 0.0, 1.0)


def _fractional_point_ci(x: float, nu: float) -> tuple[float, float]:
    """
    The 95% interval of binomial_point_ci at a fractional count or denominator, built
    the same way from the interpolated binomial tails: the effective-sample-size
    Clopper–Pearson interval of Korn and Graubard for clustered data [16].
    """
    def tails(theta):
        return fractional_binomial_tails(x, nu, theta, 0.0)

    if tails(0.5) is None:
        return math.nan, math.nan
    lo = brent(lambda t: tails(t)[1] - 0.025, 0.0, 1.0) if x > 0 else 0.0
    hi = brent(lambda t: tails(t)[0] - 0.025, 0.0, 1.0) if x < nu else 1.0
    return lo, hi
