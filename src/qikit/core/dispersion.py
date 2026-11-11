"""
dispersion.py — how much providers spread beyond chance: φ̂ and τ̂² for funnels.

Over-dispersion is estimated against the center line the funnel is drawn around [1, §5].
tau_method= chooses the estimator (docs/methods.md §4.3, §4.16, §4.17):

| tau_method     | Residuals                 | Robustness       | τ² on      | Used by                    |
|----------------|---------------------------|------------------|------------|----------------------------|
| "spiegelhalter"| Pearson, natural scale    | 10% winsorized   | the y scale| Spiegelhalter [1] (default)|
| "winsorized"   | the same, × c(0.10)       | 10% winsorized   | the y scale| qikit's calibrated option  |
| "ml"           | the chart's own likelihood| none             | the y scale| random-effects models [9]  |
| "cqc"          | √ scale (arcsine for p)   | 10% winsorized   | √ / arcsine| CQC, FunnelPlotR [13]      |
| "shmi"         | log scale                 | 10% truncated    | log        | NHS SHMI, FunnelPlotR [13] |

Numbered references are those of docs/methods.md.

[1]  Spiegelhalter DJ. Funnel plots for comparing institutional performance. Stat Med
     2005;24(8):1185-1202.
[3]  DerSimonian R, Laird N. Meta-analysis in clinical trials. Control Clin Trials
     1986;7:177-188.
[9]  Pavlou M et al. Outlier identification and monitoring of institutional or clinician
     performance. BMC Health Serv Res 2023;23:23.
[13] Mainey C. FunnelPlotR (R package), funnel_plot(sr_method=).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Final

import numpy as np

from .contours import beta_params

TAU_METHODS = ("spiegelhalter", "winsorized", "ml", "cqc", "shmi")
DEFAULT_TAU_METHOD: Final = "spiegelhalter"
# The two methods FunnelPlotR implements, which draw normal limits on a transformed scale.
TRANSFORMED_METHODS = ("cqc", "shmi")


@dataclass(frozen=True)
class Dispersion:
    """phi: the dispersion ratio as the method defines it (NaN with < 2 usable points);
    phi_raw: before the consistency factor (winsorized only, else equal to phi);
    tau2: the between-provider variance on `scale`; scale: "natural", "sqrt",
    "arcsine" or "log"."""
    phi: float
    phi_raw: float
    tau2: float
    scale: str = "natural"


def overdispersion(
    method: str, family: str, cl: float, y: np.ndarray, n: np.ndarray, mask: np.ndarray,
    center_fixed: bool = False,
) -> Dispersion:
    """
    φ̂ and τ̂² by tau_method (the ML estimate is separate: tau2_ml). center_fixed says the
    center line was given rather than pooled from these providers; the "winsorized"
    estimator then counts K rather than K − 1 degrees of freedom (no mean was estimated),
    while the published methods keep their published form, which is what reproducing a
    published funnel requires.
    """
    if method in TRANSFORMED_METHODS:
        return transformed_dispersion(method, family, cl, y, n, mask)
    published = method == "spiegelhalter"
    phi, tau2 = funnel_dispersion(
        cl, y, n, mask, family, method="spiegelhalter" if published else "winsorized",
        known_mean=center_fixed and not published,
    )
    raw = phi if published else phi / _WINSOR_CONSISTENCY
    return Dispersion(phi, raw, tau2)


# Spiegelhalter winsorizes 10% from each tail [1, eq. 6].
_WINSOR_P = 0.10


def winsor_consistency(p: float = _WINSOR_P) -> float:
    """
    c(p) = 1 / E[Z_W²] for Z ~ N(0, 1) winsorized at its p and 1 − p quantiles [1, eq. 9]:
    E[Z_W²] = (1 − 2p) − 2z·φ(z) + 2p·z², z = Φ⁻¹(1 − p). c(0.10) = 1.4735.
    """
    z = NormalDist().inv_cdf(1.0 - p)
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return 1.0 / ((1.0 - 2.0 * p) - 2.0 * z * pdf + 2.0 * p * z * z)


_WINSOR_CONSISTENCY = winsor_consistency(_WINSOR_P)


def funnel_dispersion(
    cl: float, y: np.ndarray, n: np.ndarray | None, mask: np.ndarray, family: str,
    method: str = "spiegelhalter", known_mean: bool = False,
) -> tuple[float, float]:
    """
    Spiegelhalter's over-dispersion estimate for a funnel: returns (φ̂, τ̂²).

    method="spiegelhalter" (the default) is exactly as published [1, §5].
    method="winsorized" multiplies mean(z_W²) by the Gaussian consistency factor
    c(0.10) = 1.4735 of [1, eq. 9] before the τ² = 0 gate, so φ̂ averages 1 rather than
    0.68 under pure chance (methods §4.3). Each choice is recorded in docs/methods.md:

    - Pearson residuals on the natural scale, zᵢ = (yᵢ − θ₀)/√V₀ᵢ [1, eq. 4], where
      V₀ᵢ = θ₀/nᵢ for counts ("poisson": u, oe) and θ₀(1 − θ₀)/nᵢ for proportions
      ("binomial": p). The natural scale is what makes τ² slot straight into the
      variance V₀ᵢ + τ² of [1, eq. 11].
    - 10% winsorizing, φ̂ = mean(z_W²) [1, eqs. 6, 8], so the outliers being screened
      for cannot widen the limits past themselves.
    - The debiasing factor (method="winsorized" only). Winsorizing shrinks the variance
      of a normal sample to 0.68 of its value, and [1, eq. 9] gives the correction
      w(0.10) = 1.47. [1] found it gave "somewhat wide limits" at its dozen-provider
      example and did not adopt it; without it φ̂ averages about 0.68 under pure chance,
      so the published estimator is the more sensitive screen (methods §4.3).
    - The additive random-effects variance by the method of moments [1, eq. 10; 3],
      τ̂² = (Kφ̂ − (K−1)) / (Σwᵢ − Σwᵢ²/Σwᵢ) with wᵢ = 1/V₀ᵢ, and τ̂² = 0 whenever
      φ̂ < (K−1)/K: no evidence of heterogeneity means none is assumed. It never goes
      negative, so an under-dispersed sample keeps its unadjusted limits.
    - known_mean: the center line was given, not estimated, so no degree of freedom was
      spent on it: τ̂² = K(φ̂ − 1)/Σwᵢ, 0 when φ̂ ≤ 1.

    τ̂ is the standard deviation of providers' true rates (or true O/E) around θ₀ that
    the null model does not explain, on the raw, pre-multiply scale.

    Caveat on small cohorts: winsorizing protects φ̂ from an outlier's own residual,
    but the pooled center line is not itself robust. Across a dozen providers one
    extreme performer drags it toward itself, leaving every other provider to one side
    and inflating φ̂ anyway. Passing cl= (for O/E typically 1.0, the risk model's own
    benchmark) anchors the line and removes the effect.

    φ̂ is NaN when fewer than two points carry a usable residual.
    """
    if n is None:
        raise ValueError("Over-dispersion estimation requires denominators (n=).")

    e = np.asarray(n, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        v0 = cl / e if family == "poisson" else cl * (1.0 - cl) / e
        z = (np.asarray(y, dtype=float) - cl) / np.sqrt(v0)
        w = 1.0 / v0

    valid = mask & np.isfinite(z) & np.isfinite(w)
    z_valid = z[valid]
    k = len(z_valid)
    if k < 2:
        return math.nan, 0.0

    lo, hi = np.percentile(z_valid, [100.0 * _WINSOR_P, 100.0 * (1.0 - _WINSOR_P)])
    phi = float(np.mean(np.clip(z_valid, lo, hi) ** 2))
    if method == "winsorized":
        phi *= _WINSOR_CONSISTENCY

    wv = w[valid]
    sw = float(np.sum(wv))
    if known_mean:
        return phi, max(0.0, k * (phi - 1.0) / sw)
    if k * phi <= k - 1:
        return phi, 0.0
    tau2 = (k * phi - (k - 1)) / (sw - float(np.sum(wv * wv)) / sw)
    return phi, max(0.0, tau2)


# Profile-likelihood 95% interval: the χ²₁ 0.95 point halved.
_ML_CI_DROP = 0.5 * 3.841458820694124
_ML_GRID = 80
_ML_ITERS = 60


_LGAMMA = np.frompyfunc(math.lgamma, 1, 1)


def _lgamma(x: np.ndarray) -> np.ndarray:
    """math.lgamma elementwise, on real arguments (numpy has no lgamma)."""
    return np.asarray(_LGAMMA(x), dtype=float)


def _mixture_loglik(tau: float, cl: float, o: np.ndarray, e: np.ndarray, family: str) -> float:
    """
    The marginal log-likelihood of counts o at denominators e under the chart's own
    random-effects model with spread tau around cl: Poisson–gamma (size cl²/τ²) for
    counts, beta-binomial (α + β = cl(1 − cl)/τ² − 1) for proportions; τ = 0 is the plain
    Poisson or binomial. Terms that do not involve τ are dropped. Real (effective)
    counts are allowed, through lgamma. −inf where no beta has that spread.
    """
    if family == "poisson":
        mu = cl * e
        if tau <= 0:
            return float(np.sum(o * np.log(mu) - mu))
        r = cl * cl / (tau * tau)
        return float(np.sum(
            _lgamma(o + r) - math.lgamma(r) + r * np.log(r / (r + mu))
            + o * np.log(mu / (r + mu))
        ))
    if tau <= 0:
        return float(np.sum(o * math.log(cl) + (e - o) * math.log1p(-cl)))
    params = beta_params(cl, tau * tau)
    if params is None:
        return -math.inf
    a, b = params
    s = a + b
    return float(np.sum(
        _lgamma(o + a) + _lgamma(e - o + b) - _lgamma(e + s)
    ) + len(o) * (math.lgamma(s) - math.lgamma(a) - math.lgamma(b)))


def tau2_ml(
    cl: float, y: np.ndarray, n: np.ndarray, mask: np.ndarray, family: str,
) -> tuple[float, tuple[float, float]]:
    """
    τ̂² by maximum likelihood, with its profile-likelihood 95% interval for τ:
    returns (τ̂², (lo, hi)) (methods §4.16).

    The likelihood is the one the adjusted limits are drawn from (_mixture_loglik), with
    θ₀ = cl held fixed, as the moment estimator holds it. It uses every provider's whole
    count, needs no consistency factor, and on clean data returns exactly 0 when chance
    explains the spread best. It is not robust: nothing limits an outlier's pull, so a
    single gross outlier among 30 providers, or 3% among 150, inflates τ̂ and widens the
    limits it would have crossed (methods §4.16, §5). Searched on log τ (a grid, then
    golden section), with τ = 0 compared explicitly as the boundary. (0, (nan, nan))
    when fewer than two points carry a usable count.
    """
    e = np.asarray(n, dtype=float)
    yy = np.asarray(y, dtype=float)
    ok = mask & np.isfinite(yy) & np.isfinite(e) & (e > 0)
    o, e = yy[ok] * e[ok], e[ok]
    if family == "binomial":
        o = np.clip(o, 0.0, e)
    if len(o) < 2 or not (cl > 0) or (family == "binomial" and not (cl < 1)):
        return 0.0, (math.nan, math.nan)

    def ll(t):
        return _mixture_loglik(t, cl, o, e, family)

    top = 3.0 * cl if family == "poisson" else 0.999 * math.sqrt(cl * (1.0 - cl))
    grid = np.geomspace(1e-4 * top, top, _ML_GRID)
    vals = np.array([ll(t) for t in grid])
    j = int(np.argmax(vals))
    lo_t, hi_t = grid[max(j - 1, 0)], grid[min(j + 1, len(grid) - 1)]
    g = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = math.log(lo_t), math.log(hi_t)
    for _ in range(_ML_ITERS):
        c, d = b - g * (b - a), a + g * (b - a)
        if ll(math.exp(c)) >= ll(math.exp(d)):
            b = d
        else:
            a = c
    t_hat = math.exp(0.5 * (a + b))
    l_hat = ll(t_hat)
    l_zero = ll(0.0)
    if l_zero >= l_hat:
        t_hat, l_hat = 0.0, l_zero
    target = l_hat - _ML_CI_DROP

    def crossing(inside, outside):
        # Bisection on log τ between a point above the target and one below it.
        lo, hi = math.log(inside), math.log(outside)
        for _ in range(_ML_ITERS):
            mid = 0.5 * (lo + hi)
            if ll(math.exp(mid)) >= target:
                lo = mid
            else:
                hi = mid
        return math.exp(0.5 * (lo + hi))

    anchor = t_hat if t_hat > 0 else grid[0]
    if l_zero >= target:
        ci_lo = 0.0
    else:
        below = [t for t in grid if t < anchor and ll(t) < target]
        ci_lo = crossing(anchor, below[-1]) if below else 0.0
    above = [t for t in grid if t > anchor and ll(t) < target]
    ci_hi = crossing(anchor, above[0]) if above else math.inf
    return t_hat * t_hat, (ci_lo, ci_hi)


# The dispersion-shape test (dispersion_shape below) calls clumping "within" when the
# likelihood ratio for an intercept above 1 clears the 0.1% χ²₁ point and the
# intercept itself, an estimate of φ, is at least 2. Set by simulation (methods §5):
# no false calls in 1,000+ runs of Poisson, binary-outcome and between-provider-only
# data (including heavy-tailed, lognormal provider effects) at K = 40, 200 and 1000,
# and every call on aggregated length-of-stay data with φ = 3 at K = 1000 (90% at 200).
_SHAPE_LR = 10.827566170662733  # χ²₁ 0.999 quantile
_SHAPE_MIN_PHI = 2.0
_SHAPE_MIN_K = 30
_SHAPE_CAP = 9.0               # a residual is capped at 3 of its own SDs


def _variance_line(z2: np.ndarray, e: np.ndarray, a_fixed: float | None,
                   b_free: bool = True) -> tuple[float, float, float]:
    """
    Fit Var(z) = a + b·e by iteratively reweighted least squares on z², the normal
    likelihood's own scoring step, with each z² capped at _SHAPE_CAP of its fitted
    variance so a genuine outlier cannot pose as spread. Returns (a, b, −2 log L up to
    a constant). a_fixed pins the intercept; b_free=False pins the slope at 0.
    """
    a = 1.0 if a_fixed is None else a_fixed
    b = 0.0
    for _ in range(60):
        v = a + b * e
        w = 1.0 / (v * v)
        zc = np.minimum(z2, _SHAPE_CAP * v)
        if a_fixed is None and b_free:
            x = np.column_stack([np.ones_like(e), e])
            xw = x * w[:, None]
            a, b = np.linalg.lstsq(x.T @ xw, xw.T @ zc, rcond=None)[0]
            a, b = max(float(a), 1e-3), max(float(b), 0.0)
        elif a_fixed is None:
            a = max(float(np.sum(w * zc) / np.sum(w)), 1e-3)
        else:
            b = max(0.0, float(np.sum(w * e * (zc - a)) / np.sum(w * e * e)))
    v = a + b * e
    zc = np.minimum(z2, _SHAPE_CAP * v)
    return a, b, float(np.sum(np.log(v) + zc / v))


def dispersion_shape(
    cl: float, y: np.ndarray, n: np.ndarray, mask: np.ndarray, family: str,
) -> dict:
    """
    Where a funnel's extra spread comes from, read off how it grows with volume.

    The Pearson residual zᵢ (as funnel_dispersion forms it) has variance
    a + b·nᵢ/… in two separable parts:

    - **within** — counts that clump inside each unit (patient-days: one stay adds
      many days at once) inflate every provider's variance by the same factor φ,
      whatever its volume: a = φ.
    - **between** — real differences between providers add τ² on the rate scale,
      which is nᵢτ²/V₀ on the z scale: it grows with volume, b > 0.

    The additive τ² of funnel_dispersion only models the second, so the first passes
    straight through to over-flag small providers. Fitting both by maximum likelihood
    (each residual capped at 3 of its own SDs) separates them: "within" when an
    intercept above 1 is significant (likelihood ratio > χ²₁ 0.999) and estimates
    φ ≥ 2, "between" when a slope above 0 is significant at the same level. Returns
    {"dispersion_shape": "none" | "between" | "within" | "both" | "unknown",
     "within_dispersion_hint": â}: "unknown" when the largest volume is under 1.5 times
    the smallest, too narrow a range to separate the two; {} with fewer than 30
    usable points, below the K the thresholds were calibrated at.
    """
    e = np.asarray(n, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        v0 = cl / e if family == "poisson" else cl * (1.0 - cl) / e
        z2 = (np.asarray(y, dtype=float) - cl) ** 2 / v0
        scale = e / np.nanmedian(np.where(mask & (e > 0), e, np.nan))
    ok = mask & np.isfinite(z2) & np.isfinite(scale) & (scale > 0)
    if int(np.sum(ok)) < _SHAPE_MIN_K:
        return {}
    z2, scale = z2[ok], scale[ok]
    if float(scale.max()) < 1.5 * float(scale.min()):
        # Too little spread in volume to tell a constant factor from a slope.
        a_flat, _, _ = _variance_line(z2, scale, None, b_free=False)
        return {"dispersion_shape": "unknown", "within_dispersion_hint": round(a_flat, 2)}
    a1, b1, full = _variance_line(z2, scale, None)
    _, _, unit_a = _variance_line(z2, scale, 1.0)
    _, _, flat = _variance_line(z2, scale, None, b_free=False)
    within = (unit_a - full) > _SHAPE_LR and a1 >= _SHAPE_MIN_PHI
    between = (flat - full) > _SHAPE_LR
    shape = {(False, False): "none", (False, True): "between",
             (True, False): "within", (True, True): "both"}[(within, between)]
    return {"dispersion_shape": shape, "within_dispersion_hint": round(a1, 2)}


# ---------------------------------------------------------------------------
# CQC and SHMI: residuals on a variance-stabilizing scale (FunnelPlotR)
# ---------------------------------------------------------------------------

def transform_scale(method: str, family: str) -> str:
    """The scale a transformed method works on: sqrt (counts), arcsine (proportions), log."""
    if method == "shmi":
        if family == "binomial":
            raise ValueError(
                "tau_method='shmi' is a method for ratios (O/E and rates); proportions use "
                "the arcsine scale, which is tau_method='cqc'."
            )
        return "log"
    return "arcsine" if family == "binomial" else "sqrt"


def to_scale(scale: str, v):
    """A value on the y scale, on the transformed scale."""
    v = np.asarray(v, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        if scale == "sqrt":
            return np.sqrt(v)
        if scale == "arcsine":
            return np.arcsin(np.sqrt(np.clip(v, 0.0, 1.0)))
        return np.log(v)


def from_scale(scale: str, t):
    """The inverse of to_scale, clamped to the measure's range."""
    t = np.asarray(t, dtype=float)
    if scale == "sqrt":
        return np.maximum(t, 0.0) ** 2
    if scale == "arcsine":
        return np.sin(np.clip(t, 0.0, math.pi / 2.0)) ** 2
    return np.exp(t)


def scale_sd(scale: str, cl: float, n):
    """
    The SD of a provider's value on the transformed scale under the null, s:
    1/(2√n) on the √ and arcsine scales, 1/√(θ₀n) on the log scale (FunnelPlotR's s).
    """
    n = np.asarray(n, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        if scale == "log":
            return 1.0 / np.sqrt(cl * n)
        return 1.0 / (2.0 * np.sqrt(n))


def transformed_dispersion(
    method: str, family: str, cl: float, y: np.ndarray, n: np.ndarray, mask: np.ndarray,
) -> Dispersion:
    """
    φ̂ and τ̂² as FunnelPlotR computes them for sr_method = "CQC" and "SHMI".

    zᵢ = (T(yᵢ) − T(θ₀))/sᵢ on the transformed scale T (to_scale, scale_sd). "cqc"
    winsorizes z at its 10th and 90th percentiles; "shmi" drops the providers in the
    lowest and highest tenths of the ranked z (FunnelPlotR's truncation: rank groups
    ⌊rank·10/(K + 1)⌋, keeping groups 1 to 8). φ̂ = mean(z²) over the providers kept and
    τ̂² = (Kφ̂ − (K − 1))/(Σwᵢ − Σwᵢ²/Σwᵢ), wᵢ = 1/sᵢ², 0 when Kφ̂ < K − 1, on the
    transformed scale. A provider with no events has z = −∞ on the log scale; when
    truncation keeps it, it is left out of φ̂ (FunnelPlotR would return φ̂ = ∞).
    """
    scale = transform_scale(method, family)
    e = np.asarray(n, dtype=float)
    s = scale_sd(scale, cl, e)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (to_scale(scale, y) - to_scale(scale, cl)) / s
    valid = mask & ~np.isnan(z) & np.isfinite(s) & (e > 0)
    z, s = z[valid], s[valid]
    if len(z) < 2:
        return Dispersion(math.nan, math.nan, 0.0, scale)
    if method == "cqc":
        lo, hi = np.percentile(z, [100.0 * _WINSOR_P, 100.0 * (1.0 - _WINSOR_P)])
        kept, s_kept = np.clip(z, lo, hi), s
    else:
        groups = np.floor(_average_ranks(z) * 10.0 / (len(z) + 1.0))
        keep = (groups > 0) & (groups < 9) & np.isfinite(z)
        kept, s_kept = z[keep], s[keep]
    k = len(kept)
    if k < 2:
        return Dispersion(math.nan, math.nan, 0.0, scale)
    phi = float(np.mean(kept ** 2))
    if k * phi < k - 1:
        return Dispersion(phi, phi, 0.0, scale)
    w = 1.0 / s_kept ** 2
    sw = float(np.sum(w))
    tau2 = max(0.0, (k * phi - (k - 1)) / (sw - float(np.sum(w * w)) / sw))
    return Dispersion(phi, phi, tau2, scale)


def _average_ranks(v: np.ndarray) -> np.ndarray:
    """1-based ranks with ties averaged, as R's rank(ties.method = "average")."""
    order = np.argsort(v, kind="stable")
    ranks = np.empty(len(v))
    ranks[order] = np.arange(1, len(v) + 1, dtype=float)
    vals = v[order]
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and vals[j + 1] == vals[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return ranks


def natural_tau2(scale: str, cl: float, tau2: float) -> float:
    """
    τ² carried back to the y scale by the delta method, for the shrinkage columns on a
    transformed-scale chart: 4θ₀τ² (√), 4θ₀(1 − θ₀)τ² (arcsine), θ₀²τ² (log).
    """
    if scale == "natural":
        return tau2
    if scale == "sqrt":
        return 4.0 * cl * tau2
    if scale == "arcsine":
        return 4.0 * cl * (1.0 - cl) * tau2
    return cl * cl * tau2
