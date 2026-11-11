"""
shrinkage.py — each provider's shrunk estimate: where its true value probably lies.

A funnel's signal asks "is this provider unusual?". The estimate asks "what is this
provider's true value?", and answers with the exact conjugate posterior of the chart's
own mixture model (docs/methods.md §4.14, §4.16):

    counts (O/E, rate, mean)   prior Gamma(c²/τ², rate c/τ²)   posterior Gamma(c²/τ² + O, rate c/τ² + E)
    proportions                prior Beta(α, β)                posterior Beta(α + Y, β + n − Y)

on effective counts (y/φ out of n/φ), with c the prior's center and τ² its variance.

    fit_prior()      the prior: its center, its spread, and the reference to judge against
    shrink()         reliability, posterior mean, interval and P(worse) per provider
    estimate_flag()  where each interval lies against the reference
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from .contours import beta_params
from .dispersion import natural_tau2, pooled, tau2_ml
from .dist import beta_quantile, beta_tails, gamma_quantile, gamma_tails

# Below this reliability at the largest provider, an estimated τ counts as no spread.
MIN_RELIABILITY = 0.01


@dataclass(frozen=True)
class Prior:
    """The prior the estimates shrink toward, and what they are judged against."""
    center: float         # θ₀ of the prior (the chart's center line, or the pooled value)
    tau2: float           # its variance, on the natural scale
    reference: float      # what prob_worse and estimate_flag compare with
    model: bool           # against the risk model: pooled prior, judged against 1.0
    params: tuple | None  # (α, β) of the beta prior on a proportion, else None
    binomial: bool = False

    @property
    def available(self) -> bool:
        """Whether the posterior intervals exist: a spread, and on a proportion a beta."""
        return self.tau2 > 0 and not (self.binomial and self.params is None)


def fit_prior(cl: float, ratio: np.ndarray, n_model: np.ndarray, mask: np.ndarray,
              family: str, *, model: bool, spread: bool, tau_fixed: float | None,
              tau2_chart: float, scale: str) -> Prior:
    """
    The estimates' prior (methods §4.14): its center, its spread τ², and the reference
    the estimates are judged against.

    τ² is the maximum-likelihood estimate of the chart's own mixture model around the
    prior's center, or tau_fixed when given. The limits keep the chart's tau_method: the
    published estimator understates τ, which suits a screen whose flags are reviewed,
    but would over-shrink the estimates and leave their intervals short (95% intervals
    cover 56-89% of true values under it, 91-95% under ML; methods §5).

    The center is the chart's center line cl, judged against itself. Against the risk
    model (model=True, a chart with no spread allowance) the limits stay at 1.0 with no
    τ, but the prior is centered on the providers' pooled value, with τ̂ around it; each
    provider is then judged against 1.0. Estimating τ around 1.0 would absorb any
    system-wide gap into it (§4.2.1), and the pooled value is the best guess for a
    low-volume provider in this system. A chart with neither (spread=False: no
    allowance, on a custom center) has no prior: nothing to shrink toward.

    tau2_chart and scale are the τ² the chart's limits use and the scale it is on, which
    a tau_fixed is carried back from by the delta method.
    """
    binomial = family == "binomial"
    ok = mask & np.isfinite(ratio) & (n_model > 0)
    if model:
        center, reference = pooled(ratio, n_model, ok), 1.0
    else:
        center, reference = cl, cl
    if tau_fixed is not None:
        tau2 = float(tau_fixed) if model else natural_tau2(scale, cl, tau2_chart)
    elif not spread or ok.sum() < 2:
        tau2 = 0.0
    else:
        tau2 = tau2_ml(center, ratio, n_model, ok, family)[0]
        # An estimate that would leave every provider's reliability below
        # MIN_RELIABILITY is no measurable spread: ML returns such values from the
        # numerical noise beside τ = 0, and their priors (a + b in the millions on a
        # proportion) carry nothing but cost.
        n_max = float(np.max(n_model[ok]))
        v = center * (1.0 - center) if binomial else center
        if tau2 > 0 and tau2 / (tau2 + v / n_max) < MIN_RELIABILITY:
            tau2 = 0.0
    params = beta_params(center, tau2) if binomial and tau2 > 0 else None
    return Prior(float(center), float(tau2), float(reference), model, params, binomial)


class Shrunk(NamedTuple):
    reliability: np.ndarray   # the shrinkage weight B, 0 to 1
    estimate: np.ndarray      # the posterior mean, B·y + (1 − B)·center
    low: np.ndarray           # equal-tailed posterior interval
    high: np.ndarray
    prob_worse: np.ndarray    # P(true value worse than the reference | data)


def shrink(prior: Prior, y: np.ndarray, n_model: np.ndarray, coverage: float,
           lower_is_worse: bool) -> Shrunk:
    """
    Each provider's shrunk estimate from its own value y and the denominator the model
    sees (methods §4.14). The weight is the exact conjugate posterior mean's:
    Poisson–gamma, B = τ²/(τ² + θ₀/n); beta-binomial, B = n/(n + α + β). B = 0 when
    τ² = 0: no measured spread, nothing to shrink toward, and then the interval and
    prob_worse are NaN.
    """
    c, tau2, params = prior.center, prior.tau2, prior.params
    with np.errstate(divide="ignore", invalid="ignore"):
        b: np.ndarray
        if not (tau2 > 0):
            b = np.zeros(len(y))
        elif params is not None:
            b = n_model / (n_model + params[0] + params[1])
        else:
            b = tau2 / (tau2 + (c * (1.0 - c) if prior.binomial else c) / n_model)
        estimate = b * y + (1.0 - b) * c
    low, high, prob = _posterior(prior, y * n_model, n_model, coverage, lower_is_worse)
    return Shrunk(b, estimate, low, high, prob)


def _posterior(prior: Prior, o_eff, n_eff, coverage: float, lower_is_worse: bool):
    """(low, high, P(worse)) from each provider's posterior, on effective counts."""
    k = len(o_eff)
    low, high, prob = np.full(k, np.nan), np.full(k, np.nan), np.full(k, np.nan)
    if not prior.available:
        return low, high, prob
    c, tau2, ref = prior.center, prior.tau2, prior.reference
    lo_p, hi_p = (1.0 - coverage) / 2.0, (1.0 + coverage) / 2.0
    for i, (o, n) in enumerate(zip(o_eff, n_eff)):
        if not (np.isfinite(o) and np.isfinite(n) and n > 0):
            continue
        if prior.params is not None:
            a, b = prior.params[0] + o, prior.params[1] + n - o
            low[i], high[i] = beta_quantile(lo_p, a, b), beta_quantile(hi_p, a, b)
            below, above = beta_tails(ref, a, b)
        else:
            shape, rate = c * c / tau2 + o, c / tau2 + n
            low[i] = gamma_quantile(lo_p, shape) / rate
            high[i] = gamma_quantile(hi_p, shape) / rate
            below, above = gamma_tails(shape, rate * ref)
        prob[i] = below if lower_is_worse else above
    return low, high, prob


def estimate_flag(low: np.ndarray, high: np.ndarray, reference: float,
                  worse: str | None) -> np.ndarray:
    """
    Where the interval lies against the reference: wholly above or below it, or
    across it ("no different"). With worse= the sides are "worse" and "better";
    without it, "higher" and "lower". None where there is no interval.
    """
    up, down = ("worse", "better") if worse == "higher" else (
        ("better", "worse") if worse == "lower" else ("higher", "lower"))
    out = np.full(len(low), None, dtype=object)
    ok = np.isfinite(low) & np.isfinite(high)
    out[ok] = "no different"
    out[ok & (low > reference)] = up
    out[ok & (high < reference)] = down
    return out
