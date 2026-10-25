import { ChartSpec, DispersionFamily, LimitDiag, LimitMethod, SPCInput, SPCResult } from './spc-types';
import { nanmean, nanmedian, nansum, screenedMeanMR } from './spc-helpers';
import { D2, D4, Z_80, Z_95, Z_998, a3, b3, b4, c4 } from './constants';
import {
  EXACT_MAX_LAMBDA,
  MEAN_SOLVE_MAX_K,
  betaBinomialQuantiles,
  binomialQuantiles,
  binomialThetaForCdf,
  byarQuantile,
  poissonGammaQuantiles,
  poissonMeanForCdf,
  poissonQuantileInterp,
} from './stats';

/** The two contours every funnel draws [1, §2]: lower tail, upper tail, normal deviate. */
const OUTER: [number, number, number] = [0.001, 0.999, Z_998];
const INNER: [number, number, number] = [0.025, 0.975, Z_95];
import { detectSignals } from './signals';

/**
 * Poisson funnel limits at one probability contour, on the rate (or O/E) scale.
 *
 * With nᵢ the denominator and θ₀ the center line, the count of events is modelled
 * Poisson(λᵢ = θ₀·nᵢ); the limit is that distribution's quantile divided back through
 * nᵢ [1, A.2.1]. For an O/E chart nᵢ is the expected events; for a u funnel it is the
 * exposure [1, A.2.3]. Dividing by nᵢ is what makes the funnel narrow with volume.
 *
 * Unlike 3σ limits these are asymmetric about the center line, which is the whole
 * point at low volume: a physician with 3 expected deaths has a very different amount
 * of room above the line than below it, and the normal approximation would give them
 * the same and then clip the lower limit at zero.
 *
 * Mirrors _poisson_funnel_pair in src/qikit/spc/limits.py.
 */
function poissonFunnelPair(
  cl: number, n: number[] | undefined, pLower: number, pUpper: number,
  z: number, limitMethod: LimitMethod
): [number[], number[]] {
  const e = (n ?? []).map(v => (v > 0 ? v : NaN));
  const exact = limitMethod !== 'byar';
  const ucl: number[] = [];
  const lcl: number[] = [];
  for (const ei of e) {
    const lam = cl * ei;
    if (exact && lam <= EXACT_MAX_LAMBDA) {
      ucl.push(poissonQuantileInterp(pUpper, lam) / ei);
      lcl.push(poissonQuantileInterp(pLower, lam) / ei);
    } else {
      ucl.push(byarQuantile(lam, z, true) / ei);
      lcl.push(byarQuantile(lam, z, false) / ei);
    }
  }
  return [ucl, lcl];
}

/** Linear-interpolated percentile, matching numpy.percentile's default method. */
function percentile(sorted: number[], p: number): number {
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

/**
 * Smallest true O/E this point has an 80% chance of flagging. Twin of
 * oe_detectable_ratio in limits.py.
 *
 * A funnel at physician volumes is mostly a test with no power: a physician with 5
 * expected deaths who is genuinely twice as deadly is flagged about a fifth of the
 * time, and the other four fifths a reader concludes performance was acceptable.
 * This makes that limit visible per point.
 *
 * tCount is the drawn upper limit on the count scale (ucl · E). Signals fire strictly
 * on y > ucl, so an integer count flags iff O ≥ floor(tCount) + 1, and power at true
 * ratio ρ is P(X > floor(tCount); ρE). Setting that to 0.8 and inverting the CDF in
 * its mean gives the answer exactly. 80% is fixed, not a parameter.
 */
export function oeDetectableRatio(tCount: number, e: number): number {
  if (!(e > 0) || Number.isNaN(e) || !Number.isFinite(tCount)) return NaN;

  const m = Math.floor(tCount);
  if (m < 0) return NaN;

  let lamStar: number;
  if (m <= MEAN_SOLVE_MAX_K) {
    lamStar = poissonMeanForCdf(m, 0.2);
  } else {
    // Normal approximation with continuity correction, solving λ − Z_80·√λ = m + 0.5
    // as a quadratic in √λ. Only reachable where the two agree to ~1e-5 relative.
    const s = (Z_80 + Math.sqrt(Z_80 * Z_80 + 4.0 * (m + 0.5))) / 2.0;
    lamStar = s * s;
  }
  return lamStar / e;
}

/**
 * Exact (Garwood) 95% CI for this point's own O/E. Twin of oe_point_ci in limits.py.
 *
 * Distinct from the funnel band: the band asks where this point would fall if the risk
 * model were right and the provider average, while this interval asks what range of
 * true O/E is consistent with what the provider actually did. The band is a property
 * of the null; the interval is a property of the point and does not move with θ₀.
 *
 * Falls back to Byar's closed form for non-integer counts (an averaged aggregate) or
 * counts large enough that bisection stops being worth its cost.
 */
export function oePointCi(o: number, e: number): [number, number] {
  if (!(e > 0) || Number.isNaN(e) || Number.isNaN(o) || o < 0) return [NaN, NaN];

  const oR = Math.round(o);
  const integral = Math.abs(o - oR) <= 1e-9 * Math.max(1.0, Math.abs(o));

  let muLower: number;
  let muUpper: number;
  if (integral && oR <= MEAN_SOLVE_MAX_K) {
    muLower = oR === 0 ? 0.0 : poissonMeanForCdf(oR - 1, 0.975);
    muUpper = poissonMeanForCdf(oR, 0.025);
  } else {
    muLower = o <= 0
      ? 0.0
      : o * Math.pow(Math.max(0.0, 1 - 1 / (9 * o) - Z_95 / (3 * Math.sqrt(o))), 3);
    muUpper = (o + 1) * Math.pow(
      1 - 1 / (9 * (o + 1)) + Z_95 / (3 * Math.sqrt(o + 1)), 3
    );
  }
  return [muLower / e, muUpper / e];
}

/**
 * A doubling of risk-adjusted mortality is unambiguously material. If the typical
 * point cannot detect even that, the chart cannot clear anyone, and says so.
 */
const UNDERPOWERED_RATIO = 2.0;

/**
 * Power aggregates for the summary. Twin of the oe_stats block in api.py — thresholds
 * are statements about the unscaled ratio, so multiply is divided back out.
 */
function oePowerSummary(
  detArr: number[], multiply: number, excludeMask: boolean[]
): Record<string, unknown> {
  const finite = detArr
    // Ghosted (exclude=) points are hidden from signal detection, so they are not
    // among the points this chart could flag and must not colour its power.
    .filter((_, i) => !excludeMask[i])
    .map(d => d / multiply)
    .filter(d => Number.isFinite(d))
    .sort((a, b) => a - b);
  if (finite.length === 0) return {};

  const mid = Math.floor(finite.length / 2);
  const median = finite.length % 2 === 0
    ? (finite[mid - 1] + finite[mid]) / 2
    : finite[mid];
  const nUnder = finite.filter(d => d > UNDERPOWERED_RATIO).length;
  const underpowered = median > UNDERPOWERED_RATIO;

  return {
    min_detectable_oe_median: median,
    n_underpowered: nUnder,
    underpowered,
    // Composed here rather than left to the caller so a consuming agent, or a report
    // generator, can quote one sentence instead of reconstructing the interpretation.
    ...(underpowered ? {
      power_note:
        `${nUnder} of ${finite.length} points have too few expected events to detect ` +
        `even a doubling of risk (smallest detectable O/E, median: ${median.toFixed(1)}). ` +
        `Absence of a signal is not evidence of acceptable performance; aggregate more ` +
        `time periods or compare at a higher level before drawing conclusions.`,
    } : {}),
  };
}

/** x as an integer when it is one to within float noise, else null. */
function integerCount(x: number): number | null {
  const r = Math.round(x);
  return Math.abs(x - r) <= 1e-9 * Math.max(1.0, Math.abs(x)) ? r : null;
}

/**
 * Smallest true proportion this point has an 80% chance of flagging on a p funnel.
 * Twin of binomial_detectable_rate in limits.py: the θ at which
 * F(floor(tCount); n, θ) = 0.2. Infinity when no count can flag (the limit sits at
 * or above n); NaN without a usable, integer denominator. A u funnel reuses
 * oeDetectableRatio, whose Poisson algebra is the same with exposure for E.
 */
export function binomialDetectableRate(tCount: number, n: number): number {
  if (!(n > 0) || !Number.isFinite(tCount)) return NaN;
  const m = integerCount(n);
  if (m === null) return NaN;
  const thr = Math.floor(tCount);
  if (thr < 0) return NaN;
  if (thr >= m) return Infinity;
  return binomialThetaForCdf(thr, m, 0.2);
}

/**
 * Exact (Clopper–Pearson) 95% CI for this point's own proportion. Twin of
 * binomial_point_ci: x = 0 gives a lower bound of exactly 0, x = n an upper bound of
 * exactly 1; NaN for a non-integer count or denominator.
 */
export function binomialPointCi(x: number, n: number): [number, number] {
  if (!(n > 0) || Number.isNaN(x) || x < 0 || x > n) return [NaN, NaN];
  const m = integerCount(n);
  const k = integerCount(x);
  if (m === null || k === null) return [NaN, NaN];
  const lo = k === 0 ? 0.0 : binomialThetaForCdf(k - 1, m, 0.975);
  const hi = k === m ? 1.0 : binomialThetaForCdf(k, m, 0.025);
  return [lo, hi];
}

/** Median of an ascending array, as numpy.median takes it. */
function sortedMedian(sorted: number[]): number {
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

/**
 * The underpowered verdict for a p/u funnel. Twin of _funnel_power_summary in
 * api.py: judged relative to the center line (min_detectable / cl > 2), on raw
 * arrays, with unflaggable (Infinity) points counted and ghosted points left out.
 */
function funnelPowerSummary(
  chart: string, detArr: number[], clArr: number[], excludeMask: boolean[]
): Record<string, unknown> {
  const counted = detArr
    .map((d, i) => d / (clArr[i] > 0 ? clArr[i] : NaN))
    .filter((r, i) => !excludeMask[i] && !Number.isNaN(r))
    .sort((a, b) => a - b);
  if (counted.length === 0) return {};

  const median = sortedMedian(counted);
  const nUnder = counted.filter(r => r > UNDERPOWERED_RATIO).length;
  const underpowered = median > UNDERPOWERED_RATIO;
  const noun = chart === 'p' || chart === 'pp' ? 'proportion' : 'rate';
  const reach = Number.isFinite(median)
    ? `median: ${median.toFixed(1)}× the center line`
    : 'median: none, most points cannot flag at all';
  return {
    // NaN (null) only when over half the points cannot flag at all.
    min_detectable_ratio_median: Number.isFinite(median) ? median : NaN,
    n_underpowered: nUnder,
    underpowered,
    ...(underpowered ? {
      power_note:
        `${nUnder} of ${counted.length} points have too few cases to detect even a ` +
        `doubling of the center-line ${noun} (smallest detectable ${noun}, ${reach}). ` +
        `Absence of a signal is not evidence of acceptable performance; aggregate ` +
        `more time periods or compare at a higher level before drawing conclusions.`,
    } : {}),
  };
}

/**
 * Exact binomial funnel limits at one contour, on the proportion scale [1, A.1.1].
 * A non-integer denominator falls back to [1] eq. 3 and says so through diag.
 * Mirrors _binomial_funnel_pair in limits.py.
 */
function binomialFunnelPair(
  cl: number, n: number[] | undefined, pLower: number, pUpper: number, z: number,
  diag?: LimitDiag
): [number[], number[]] {
  const ucl: number[] = [];
  const lcl: number[] = [];
  for (const ni of n ?? []) {
    if (!(ni > 0)) {
      ucl.push(NaN);
      lcl.push(NaN);
      continue;
    }
    const [[lo, hi], exact] = binomialQuantiles([pLower, pUpper], ni, cl, [-z, z]);
    if (!exact && diag) diag.normal = true;
    ucl.push(hi / ni);
    lcl.push(lo / ni);
  }
  return [ucl, lcl];
}

/**
 * Spiegelhalter's over-dispersion estimate for a funnel: returns [φ̂, τ̂²]. Twin of
 * funnel_dispersion in limits.py, whose docstring records each choice: Pearson
 * residuals on the natural scale [1, eq. 4], 10% winsorized φ̂ [1, eqs. 6, 8] with no
 * debiasing factor (as [1] did not adopt one), and the method-of-moments τ̂² [1, eq. 10]
 * with τ̂² = 0 whenever φ̂ < (K−1)/K. φ̂ is NaN with fewer than two usable points.
 */
export function funnelDispersion(
  cl: number, y: number[], n: number[] | undefined, mask: boolean[], family: DispersionFamily
): [number, number] {
  if (!n) throw new Error('Over-dispersion estimation requires denominators (n).');

  const z: number[] = [];
  const w: number[] = [];
  for (let i = 0; i < y.length; i++) {
    if (!mask[i]) continue;
    const v0 = family === 'poisson' ? cl / n[i] : cl * (1.0 - cl) / n[i];
    const zi = (y[i] - cl) / Math.sqrt(v0);
    const wi = 1.0 / v0;
    if (Number.isFinite(zi) && Number.isFinite(wi)) {
      z.push(zi);
      w.push(wi);
    }
  }

  const k = z.length;
  if (k < 2) return [NaN, 0.0];

  const sorted = [...z].sort((a, b) => a - b);
  const lo = percentile(sorted, 10);
  const hi = percentile(sorted, 90);
  let total = 0;
  for (const zi of z) {
    const c = Math.min(hi, Math.max(lo, zi));
    total += c * c;
  }
  const phi = total / k;

  if (k * phi <= k - 1) return [phi, 0.0];
  let sw = 0;
  let sw2 = 0;
  for (const wi of w) {
    sw += wi;
    sw2 += wi * wi;
  }
  const tau2 = (k * phi - (k - 1)) / (sw - sw2 / sw);
  return [phi, Math.max(0.0, tau2)];
}

/**
 * Over-dispersed funnel limits at one contour: [1, eq. 11]'s additive random-effects
 * model drawn exactly — Poisson–gamma for counts, beta-binomial for proportions — rather
 * than as a normal approximation. τ² = 0 delegates to the unadjusted limits, so the two
 * charts agree exactly without evidence of over-dispersion. Mirrors _mixture_funnel_pair
 * in limits.py, whose docstring explains the model.
 */
function mixtureFunnelPair(
  cl: number, n: number[] | undefined, tau2: number, family: DispersionFamily,
  pLower: number, pUpper: number, z: number, diag?: LimitDiag
): [number[], number[]] {
  if (!(tau2 > 0)) {
    return family === 'binomial'
      ? binomialFunnelPair(cl, n, pLower, pUpper, z, diag)
      : poissonFunnelPair(cl, n, pLower, pUpper, z, 'exact');
  }

  const ucl: number[] = [];
  const lcl: number[] = [];
  const e = n ?? [];

  if (family === 'poisson') {
    const size = cl * cl / tau2;
    for (const ei of e) {
      if (!(ei > 0)) {
        ucl.push(NaN);
        lcl.push(NaN);
        continue;
      }
      const [[lo, hi], exact] = poissonGammaQuantiles([pLower, pUpper], cl * ei, size, [-z, z]);
      if (!exact && diag) diag.normal = true;
      ucl.push(hi / ei);
      lcl.push(lo / ei);
    }
    return [ucl, lcl];
  }

  const s = cl * (1.0 - cl) / tau2 - 1.0;
  if (!(s > 0)) {
    // No beta distribution has this mean and variance; fall back to [1, eq. 11].
    if (diag) diag.normal = true;
    for (const ei of e) {
      const half = z * Math.sqrt(cl * (1.0 - cl) / (ei > 0 ? ei : NaN) + tau2);
      ucl.push(cl + half);
      lcl.push(cl - half);
    }
    return [ucl, lcl];
  }

  const alpha = cl * s;
  const beta = (1.0 - cl) * s;
  for (const ei of e) {
    if (!(ei > 0)) {
      ucl.push(NaN);
      lcl.push(NaN);
      continue;
    }
    const [[lo, hi], exact] = betaBinomialQuantiles([pLower, pUpper], ei, alpha, beta, [-z, z]);
    if (!exact && diag) diag.normal = true;
    ucl.push(hi / ei);
    lcl.push(lo / ei);
  }
  return [ucl, lcl];
}

/** Weighted center line Σ(yᵢnᵢ)/Σnᵢ, shared by every attribute chart. */
const weightedCenter = (yb: number[], nb?: number[]) =>
  nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!);

/** x to two significant figures in fixed notation. Twin of _two_sig in api.py. */
function twoSig(x: number): string {
  if (!(x > 0) || !Number.isFinite(x)) return x.toFixed(2);
  return x.toFixed(Math.max(0, 1 - Math.floor(Math.log10(x))));
}

/**
 * Unadjusted charts with an over-dispersion-adjusted counterpart, and how
 * dispersion_note names what they compare. Mirrors _DISPERSION_NOTE in api.py.
 */
const DISPERSION_NOTE: Record<string, [string, string, string]> = {
  oe: ["chart='oep'", 'the risk model and chance', 'O/E'],
  p: ["chart='pp' with funnel=True", 'chance', 'proportions'],
  u: ["chart='up' with funnel=True", 'chance', 'rates'],
};

/**
 * Per-point subgroup sizes, preferring the n array over the scalar fallback.
 * NaN when neither is available — the constant accessors turn that into NaN limits.
 */
function subgroupSizes(n: number[] | undefined, subN: number | undefined, k: number): number[] {
  if (n) return n;
  return new Array(k).fill(subN ?? NaN);
}

/**
 * Volume-weighted grand mean Σ(nᵢx̄ᵢ)/Σnᵢ for the Xbar chart. Identical to the
 * unweighted mean when subgroup sizes are constant, correct when they are not.
 */
function grandMean(yBase: number[], nBase?: number[]): number {
  if (!nBase) return nanmean(yBase);
  let num = 0;
  let den = 0;
  for (let i = 0; i < yBase.length; i++) {
    if (Number.isNaN(yBase[i]) || Number.isNaN(nBase[i])) continue;
    num += yBase[i] * nBase[i];
    den += nBase[i];
  }
  return den === 0 ? NaN : num / den;
}

/**
 * I chart limits: σ̂ = MR̄/d2 (Montgomery 2019, §6.2; d2 = 1.128 for n = 2).
 * Shared by the i and ip charts, which differ only in their center line.
 */
function iLimits(cl: number, y: number[], mask: boolean[]): [number[], number[]] {
  const mrBar = screenedMeanMR(y, mask);
  const sigma = mrBar / D2[2];
  if (!(sigma > 0)) {
    // A perfectly flat series has no variation to estimate a spread from.
    // Zero-width limits would draw three coincident lines and call any
    // departure a signal, so report no limits and let it read as a run chart.
    // The !(> 0) form also catches the NaN mrBar case (fewer than 2 points).
    return [new Array(y.length).fill(NaN), new Array(y.length).fill(NaN)];
  }
  return [new Array(y.length).fill(cl + 3 * sigma), new Array(y.length).fill(cl - 3 * sigma)];
}

export const CHARTS: Record<string, ChartSpec> = {
  run: {
    center: (yb) => nanmedian(yb),
    limits: (_cl, y) => [new Array(y.length).fill(NaN), new Array(y.length).fill(NaN)],
    needsN: false, isAttribute: false, floorLcl: false
  },
  i: {
    center: (yb) => nanmean(yb),
    limits: (cl, y, _n, mask) => iLimits(cl, y, mask),
    needsN: false, isAttribute: false, floorLcl: false
  },
  mr: {
    center: (yb) => nanmean(yb),
    limits: (cl, y) => [new Array(y.length).fill(D4[2] * cl), new Array(y.length).fill(NaN)],
    needsN: false, isAttribute: false, floorLcl: false
  },
  p: {
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, _y, n) => {
      const ucl = n!.map(ni => cl + 3 * Math.sqrt(cl * (1 - cl) / ni));
      const lcl = n!.map(ni => cl - 3 * Math.sqrt(cl * (1 - cl) / ni));
      return [ucl, lcl];
    },
    needsN: true, isAttribute: true, floorLcl: true
  },
  u: {
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, _y, n) => {
      const ucl = n!.map(ni => cl + 3 * Math.sqrt(cl / ni));
      const lcl = n!.map(ni => cl - 3 * Math.sqrt(cl / ni));
      return [ucl, lcl];
    },
    needsN: true, isAttribute: true, floorLcl: true
  },
  c: {
    center: (yb) => nanmean(yb),
    limits: (cl, y) => {
      const sigma = Math.sqrt(Math.max(cl, 0));
      return [new Array(y.length).fill(cl + 3 * sigma), new Array(y.length).fill(cl - 3 * sigma)];
    },
    needsN: false, isAttribute: false, floorLcl: true
  },
  g: {
    center: (yb) => nanmedian(yb),
    limits: (cl, y) => {
      const sigma = Math.sqrt(Math.max(cl * (cl + 1), 0));
      return [new Array(y.length).fill(cl + 3 * sigma), new Array(y.length).fill(cl - 3 * sigma)];
    },
    needsN: false, isAttribute: false, floorLcl: true
  },
  pp: {
    // Laney p' chart: σ'ᵢ = √(p̄(1−p̄)/nᵢ)·σ_z, σ_z = max(1, MR̄(z)/d2). Laney (2002).
    // The floor keeps p' from coming out *narrower* than the naive p chart on an
    // underdispersed sample — the method only ever widens.
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, y, n, mask) => {
      const sigmaBase = n!.map(ni => Math.sqrt(cl * (1 - cl) / ni));
      const z = y.map((v, i) => (v - cl) / sigmaBase[i]);
      const zValid = z.filter((v, i) => mask[i] && !isNaN(v));
      let sigmaZ = 1.0;
      if (zValid.length > 1) {
        const mrs = [];
        for (let i = 1; i < zValid.length; i++) mrs.push(Math.abs(zValid[i] - zValid[i - 1]));
        sigmaZ = Math.max(1.0, nanmean(mrs) / D2[2]);
      }
      return [sigmaBase.map(s => cl + 3 * s * sigmaZ), sigmaBase.map(s => cl - 3 * s * sigmaZ)];
    },
    needsN: true, isAttribute: true, floorLcl: true
  },
  up: {
    // Laney u' chart: σ'ᵢ = √(ū/nᵢ)·σ_z, σ_z = max(1, MR̄(z)/d2). Laney (2002).
    // Same floor as pp: an underdispersed sample falls back to the naive u limits.
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, y, n, mask) => {
      const sigmaBase = n!.map(ni => Math.sqrt(cl / ni));
      const z = y.map((v, i) => (v - cl) / sigmaBase[i]);
      const zValid = z.filter((v, i) => mask[i] && !isNaN(v));
      let sigmaZ = 1.0;
      if (zValid.length > 1) {
        const mrs = [];
        for (let i = 1; i < zValid.length; i++) mrs.push(Math.abs(zValid[i] - zValid[i - 1]));
        sigmaZ = Math.max(1.0, nanmean(mrs) / D2[2]);
      }
      return [sigmaBase.map(s => cl + 3 * s * sigmaZ), sigmaBase.map(s => cl - 3 * s * sigmaZ)];
    },
    needsN: true, isAttribute: true, floorLcl: true
  },
  xbar: {
    // UCL = X̄̄ + A3(nᵢ)·S̄, LCL = X̄̄ − A3(nᵢ)·S̄. Montgomery (2019), §6.4.
    // With unequal subgroup sizes the caller supplies a pooled σ̂ instead of S̄ and
    // limits become X̄̄ ± 3σ̂/√nᵢ. The two must not be mixed: A3 = 3/(c4√n) already
    // embeds the correction for the bias of an arithmetic mean of subgroup SDs.
    center: (yb, nb) => grandMean(yb, nb),
    limits: (cl, y, n, _mask, subN, sBar, sigmaHat) => {
      const sizes = subgroupSizes(n, subN, y.length);
      if (sigmaHat !== undefined) {
        const half = sizes.map(ni => (3 * sigmaHat) / Math.sqrt(ni >= 2 ? ni : NaN));
        return [half.map(h => cl + h), half.map(h => cl - h)];
      }
      const a = sizes.map(ni => a3(ni));
      return [a.map(v => cl + v * sBar!), a.map(v => cl - v * sBar!)];
    },
    needsN: false, isAttribute: false, floorLcl: false
  },
  s: {
    // UCL = B4(nᵢ)·S̄, LCL = B3(nᵢ)·S̄, CL = S̄. Montgomery (2019), §6.4.
    // Unequal sizes express the whole chart against a pooled σ̂ instead:
    //   CL = c4(nᵢ)·σ̂ (the third return element), U/L = CL ± 3σ̂·√(1 − c4(nᵢ)²).
    // The center line has to vary too — E[sᵢ] = c4(nᵢ)·σ̂ climbs with n, and the CL
    // feeds the runs detector, which is a pure side-of-CL test.
    center: (yb) => nanmean(yb),
    limits: (cl, y, n, _mask, subN, _sBar, sigmaHat) => {
      const sizes = subgroupSizes(n, subN, y.length);
      if (sigmaHat !== undefined) {
        const clI = sizes.map(ni => sigmaHat * c4(ni));
        const half = sizes.map(ni => 3 * sigmaHat * Math.sqrt(Math.max(0, 1 - c4(ni) * c4(ni))));
        return [
          clI.map((c, i) => c + half[i]),
          clI.map((c, i) => Math.max(0, c - half[i])),
          clI,
        ];
      }
      return [sizes.map(ni => b4(ni) * cl), sizes.map(ni => b3(ni) * cl)];
    },
    needsN: false, isAttribute: false, floorLcl: true
  },
  ip: {
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, y, _n, mask) => iLimits(cl, y, mask),
    needsN: true, isAttribute: true, floorLcl: false
  },
  oe: {
    // Pooled ΣO/ΣE. isAttribute divides y by n upstream, so yBase is already the
    // per-point ratio and this weights it back by expected volume.
    center: weightedCenter,
    limits: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, limitMethod) =>
      poissonFunnelPair(cl, n, ...OUTER, limitMethod ?? 'exact'),
    limits95: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, limitMethod) =>
      poissonFunnelPair(cl, n, ...INNER, limitMethod ?? 'exact'),
    needsN: true, isAttribute: true, floorLcl: true, family: 'poisson'
  },
  oep: {
    center: weightedCenter,
    limits: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, _lm, tau2, diag) =>
      mixtureFunnelPair(cl, n, tau2 ?? 0, 'poisson', ...OUTER, diag),
    limits95: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, _lm, tau2, diag) =>
      mixtureFunnelPair(cl, n, tau2 ?? 0, 'poisson', ...INNER, diag),
    needsN: true, isAttribute: true, floorLcl: true, family: 'poisson', adjusted: true
  }
};

/**
 * What p, pp, u and up become with funnel=true: Spiegelhalter's probability contours
 * [1] instead of 3σ, and for pp/up his additive over-dispersion adjustment instead of
 * Laney's σ_z, whose moving ranges only mean something in time order. Mirrors
 * FUNNEL_CHARTS in limits.py; the time-ordered CHARTS entries are untouched.
 */
export const FUNNEL_CHARTS: Record<string, ChartSpec> = {
  p: {
    center: weightedCenter,
    limits: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, _lm, _tau2, diag) =>
      binomialFunnelPair(cl, n, ...OUTER, diag),
    limits95: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, _lm, _tau2, diag) =>
      binomialFunnelPair(cl, n, ...INNER, diag),
    needsN: true, isAttribute: true, floorLcl: true, family: 'binomial'
  },
  pp: {
    center: weightedCenter,
    limits: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, _lm, tau2, diag) =>
      mixtureFunnelPair(cl, n, tau2 ?? 0, 'binomial', ...OUTER, diag),
    limits95: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, _lm, tau2, diag) =>
      mixtureFunnelPair(cl, n, tau2 ?? 0, 'binomial', ...INNER, diag),
    needsN: true, isAttribute: true, floorLcl: true, family: 'binomial', adjusted: true
  },
  u: {
    center: weightedCenter,
    limits: (cl, _y, n) => poissonFunnelPair(cl, n, ...OUTER, 'exact'),
    limits95: (cl, _y, n) => poissonFunnelPair(cl, n, ...INNER, 'exact'),
    needsN: true, isAttribute: true, floorLcl: true, family: 'poisson'
  },
  up: {
    center: weightedCenter,
    limits: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, _lm, tau2, diag) =>
      mixtureFunnelPair(cl, n, tau2 ?? 0, 'poisson', ...OUTER, diag),
    limits95: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, _lm, tau2, diag) =>
      mixtureFunnelPair(cl, n, tau2 ?? 0, 'poisson', ...INNER, diag),
    needsN: true, isAttribute: true, floorLcl: true, family: 'poisson', adjusted: true
  }
};

export function compute(input: SPCInput): SPCResult {
  let { y, n, chart, method = 'anhoej', freeze, part, exclude = [], clOverride, multiply = 1.0, sBar, sigmaHat, subgroupN, funnel = false } = input;

  if (input.limitMethod !== undefined && chart === 'oep') {
    throw new Error(
      'limitMethod is not available for chart "oep". Its limits are always exact ' +
      'Poisson–gamma quantiles, which have no Byar counterpart. Use chart "oe" for ' +
      'exact or Byar limits without the over-dispersion adjustment.'
    );
  }
  if (input.limitMethod !== undefined && chart !== 'oe') {
    throw new Error(
      `limitMethod is only valid for chart "oe". Got chart "${chart}". ` +
      `Funnel plots of the other charts always use exact limits, and time-ordered ` +
      `charts use 3σ limits, which have no quantile method to choose.`
    );
  }
  const limitMethod: LimitMethod = input.limitMethod ?? 'exact';
  if (chart === 'oe' && limitMethod !== 'exact' && limitMethod !== 'byar') {
    throw new Error(`limitMethod must be "exact" or "byar", got "${limitMethod}".`);
  }

  // Resolved display hints (mirrors Python qic() semantics)
  const yPercent = input.yPercent ?? (chart === 'p' || chart === 'pp');
  const connect = funnel ? false : (input.connect ?? null);
  const spec = (funnel && FUNNEL_CHARTS[chart]) || CHARTS[chart === 't' ? 'i' : chart];

  if (!Array.isArray(y)) {
      y = Object.values(y); // Handle case where it might be a Series-like object from JSON
  }

  let yCalc = [...y];
  
  // Handle n being a single number or an array
  let nCalc: number[] | undefined = undefined;
  if (n !== undefined) {
    if (Array.isArray(n)) {
      nCalc = [...n];
    } else {
      nCalc = new Array(y.length).fill(n);
    }
  }

  if (spec.needsN && !nCalc) {
    throw new Error(`Chart type "${chart}" requires a sample size column (N).`);
  }

  // Funnel mode: cross-sectional comparison — order points by denominator ascending.
  // Mirrors src/qikit/spc/api.py; proven by fixtures/spc/funnel_*.json on both sides.
  if (funnel) {
    if (!['p', 'pp', 'u', 'up', 'oe', 'oep'].includes(chart)) {
      throw new Error(`funnel=true is only valid for attribute charts with denominators (p, pp, u, up, oe, oep). Got chart "${chart}".`);
    }
    if (!nCalc) {
      throw new Error('funnel=true requires denominators (n).');
    }
    if (freeze !== undefined || part !== undefined) {
      throw new Error('funnel=true cannot be combined with freeze or part. A funnel plot is a cross-sectional comparison ordered by denominator; freeze and part are temporal/phase concepts that assume the points are in time order.');
    }
    const order = nCalc.map((_, i) => i).sort((a, b) => nCalc![a] - nCalc![b]);
    y = order.map(i => (y as number[])[i]);
    yCalc = order.map(i => yCalc[i]);
    nCalc = order.map(i => nCalc![i]);

    // exclude is 1-based into the *input* order; invert the sort permutation so the
    // named point stays ghosted after the reorder. Mirrors src/qikit/spc/api.py.
    const newPos = new Array<number>(order.length);
    order.forEach((orig, pos) => { newPos[orig] = pos; });
    const exArr = Array.isArray(exclude) ? exclude : [exclude];
    exclude = exArr.map(i => (i >= 1 && i <= order.length ? newPos[i - 1] + 1 : i));
  }

  let mask = new Array(y.length).fill(true);
  const excludeArr = Array.isArray(exclude) ? exclude : [exclude];
  const partArr = part ? (Array.isArray(part) ? part : [part]) : undefined;
  // exclude= drops a point from the baseline *and* ghosts it out of signal
  // detection; freeze/part only narrow the baseline, and their boundary points
  // must still be checked against it. Mirrors src/qikit/spc/compute.py.
  let excludeMask = new Array(y.length).fill(false);
  excludeArr.forEach(i => {
    if (i >= 1 && i <= y.length) {
      mask[i - 1] = false;
      excludeMask[i - 1] = true;
    }
  });
  if (freeze) {
    for (let i = freeze; i < y.length; i++) mask[i] = false;
  }

  // Handle xbar/s aggregation (subgrouping)
  if ((chart === 'xbar' || chart === 's') && subgroupN) {
    const yAgg = [];
    const nAgg = [];
    const sdAgg = [];
    const maskAgg = [];
    const exAgg = [];
    for (let i = 0; i < y.length; i += subgroupN) {
      const chunk = y.slice(i, i + subgroupN);
      if (chunk.length === 0) continue;

      const m = nanmean(chunk);
      const sqDiffs = chunk.map(v => Math.pow(v - m, 2));
      const sd = Math.sqrt(nansum(sqDiffs) / (chunk.length - 1));
      yAgg.push(chart === 'xbar' ? m : sd);
      sdAgg.push(sd);
      // A trailing partial chunk is genuinely smaller — record its real size so the
      // limits functions pick the matching constant rather than subgroupN's.
      nAgg.push(chunk.length);
      maskAgg.push(mask[i]);
      exAgg.push(excludeMask[i]);
    }
    yCalc = yAgg;
    nCalc = nAgg;
    y = [...yAgg];
    mask = [...maskAgg];
    excludeMask = [...exAgg];

    // Derive the sigma estimate when the caller supplied neither. Mirrors
    // _sigma_estimate() in src/qikit/spc/api.py: equal subgroup sizes get the
    // classical S̄ = mean(sᵢ) that pairs with A3/B3/B4; unequal sizes get the pooled
    // σ̂ = Sp/c4(d+1), which pairs with the 3σ̂/√nᵢ form instead.
    if (sBar === undefined && sigmaHat === undefined) {
      const usableSizes: number[] = [];
      const usableSds: number[] = [];
      for (let i = 0; i < nAgg.length; i++) {
        if (nAgg[i] >= 2 && !Number.isNaN(sdAgg[i])) {
          usableSizes.push(nAgg[i]);
          usableSds.push(sdAgg[i]);
        }
      }
      if (usableSizes.length > 0) {
        if (new Set(usableSizes).size === 1) {
          sBar = nanmean(usableSds);
        } else {
          let ss = 0;
          let dof = 0;
          usableSizes.forEach((ni, i) => {
            ss += (ni - 1) * usableSds[i] * usableSds[i];
            dof += ni - 1;
          });
          sigmaHat = Math.sqrt(ss / dof) / c4(dof + 1);
        }
      }
    }
  }

  // Transforms
  if (chart === 'mr') {
    const yNew = [];
    for (let i = 1; i < y.length; i++) yNew.push(Math.abs(y[i] - y[i - 1]));
    yCalc = yNew;
    const maskNew = [];
    for (let i = 1; i < mask.length; i++) maskNew.push(mask[i] && mask[i - 1]);
    // Each range spans two points, so it is ghosted if either endpoint was.
    const exNew = [];
    for (let i = 1; i < excludeMask.length; i++) exNew.push(excludeMask[i] || excludeMask[i - 1]);
    excludeMask = exNew;
    // Note: X-axis would also be shortened in a real UI
    y = y.slice(1);
    nCalc = undefined;
    // We update mask for limits calculation
    mask.splice(0, mask.length, ...maskNew);
  }

  if (spec.isAttribute && nCalc) {
    yCalc = yCalc.map((v, i) => nCalc![i] > 0 ? v / nCalc![i] : NaN);
  }

  if (chart === 't') {
    yCalc = yCalc.map(v => Math.pow(v, 1 / 3.6));
  }

  const nPts = yCalc.length;
  const boundaries = [0, ...(partArr ? partArr.map(p => p - 1) : []), nPts].sort((a, b) => a - b);
  
  const clArr = new Array(nPts).fill(NaN);
  const uclArr = new Array(nPts).fill(NaN);
  const lclArr = new Array(nPts).fill(NaN);
  const ucl95Arr = new Array(nPts).fill(NaN);
  const lcl95Arr = new Array(nPts).fill(NaN);
  const sigmaSig = new Array(nPts).fill(false);
  const runsSig = new Array(nPts).fill(false);
  const runsLoc = new Array(nPts).fill(false);
  const summaries: any[] = [];

  for (let i = 0; i < boundaries.length - 1; i++) {
    const s = boundaries[i];
    const e = boundaries[i + 1];
    const segY = yCalc.slice(s, e);
    const segN = nCalc ? nCalc.slice(s, e) : undefined;
    const segMask = mask.slice(s, e);
    
    const yBase = segY.filter((_, idx) => segMask[idx]);
    const nBase = segN ? segN.filter((_, idx) => segMask[idx]) : undefined;
    
    // clOverride should be applied per point if it's already an array, 
    // but in SPCInput it's a single number.
    let clVal = clOverride !== undefined ? clOverride : spec.center(yBase, nBase);
    
    // For t-chart override, transform it to the same space as yCalc
    if (chart === 't' && clOverride !== undefined) {
        clVal = Math.pow(clOverride, 1 / 3.6);
    }
    
    // Over-dispersion, estimated once per segment against the center line it is drawn
    // around [1, §5]: a diagnostic on an unadjusted funnel, the limits' input on an
    // adjusted one. Mirrors compute.py.
    const segExtra: Record<string, unknown> = {};
    let tau2 = 0.0;
    if (spec.family && segN) {
      const [phi, t2] = funnelDispersion(clVal, segY, segN, segMask, spec.family);
      tau2 = t2;
      segExtra.dispersion_phi = phi;
      segExtra.dispersion_tau = Math.sqrt(t2);
      segExtra.overdispersed = t2 > 0;
      if (spec.adjusted) {
        segExtra.dispersion_method = 'additive';
        segExtra.dispersion_adjusted = t2 > 0;
      }
    } else if (chart === 'pp' || chart === 'up') {
      // The same chart code means a different method in time order; say which.
      segExtra.dispersion_method = 'laney';
    }
    const diag: LimitDiag = {};
    const tau2Arg = spec.adjusted ? tau2 : 0.0;

    // Limits
    // Important: for t-chart, we need to pass clVal which is in transformed space
    const [uclSeg, lclSeg, clSeg] = spec.limits(clVal, segY, segN, segMask, subgroupN, sBar, sigmaHat, limitMethod, tau2Arg, diag);

    // A chart whose limits come from a distribution supplies its own 95% band; the
    // 2/3-of-3σ shortcut below holds only for symmetric, normal limits.
    const band95 = spec.limits95
      ? spec.limits95(clVal, segY, segN, segMask, subgroupN, sBar, sigmaHat, limitMethod, tau2Arg, diag)
      : undefined;
    if (spec.limits95) {
      // Which method drew the limits is not recoverable from the numbers alone, and a
      // funnel is the kind of chart that ends up in a credentialing file. Record it.
      segExtra.limit_method = diag.normal ? 'normal' : (chart === 'oe' ? limitMethod : 'exact');
    }

    for (let j = 0; j < e - s; j++) {
      // clSeg is present only for charts whose center line varies per point; an
      // explicit clOverride is the user's line and outranks it.
      const clHere = (clOverride === undefined && clSeg) ? clSeg[j] : clVal;
      clArr[s + j] = clHere;
      uclArr[s + j] = uclSeg[j];
      lclArr[s + j] = spec.floorLcl ? Math.max(0, lclSeg[j]) : lclSeg[j];
      let u95: number;
      let l95: number;
      if (band95) {
        u95 = band95[0][j];
        l95 = band95[1][j];
      } else {
        const spread = uclSeg[j] - clHere;
        u95 = clHere + spread * (2 / 3);
        l95 = clHere - spread * (2 / 3);
      }
      ucl95Arr[s + j] = u95;
      lcl95Arr[s + j] = spec.floorLcl ? Math.max(0, l95) : l95;
    }

    // Signals per segment — ghosted (exclude=) points are hidden from detection
    // entirely, so they neither flag nor break a run. Mirrors compute.py.
    const segSignalY = segY.map((v, j) => (excludeMask[s + j] ? NaN : v));
    const { signals: sSig, signalsLocalized: sLoc, summary: sSum } = detectSignals(segSignalY, clArr.slice(s, e), method, uclArr.slice(s, e), lclArr.slice(s, e));
    for (let j = 0; j < e - s; j++) {
      runsSig[s + j] = sSig[j];
      runsLoc[s + j] = sLoc[j];
      sigmaSig[s + j] = (!isNaN(uclArr[s + j]) && segSignalY[j] > uclArr[s + j]) || (!isNaN(lclArr[s + j]) && segSignalY[j] < lclArr[s + j]);
    }
    summaries.push({ ...sSum, ...segExtra });
  }

  // Back-transform for t-chart
  if (chart === 't') {
    for (let i = 0; i < nPts; i++) {
      clArr[i]   = Math.pow(Math.max(0, clArr[i]),   3.6);
      uclArr[i]  = Math.pow(Math.max(0, uclArr[i]),  3.6);
      lclArr[i]  = Math.pow(Math.max(0, lclArr[i]),  3.6);
      ucl95Arr[i] = Math.pow(Math.max(0, ucl95Arr[i]), 3.6);
      lcl95Arr[i] = Math.pow(Math.max(0, lcl95Arr[i]), 3.6);
    }
  }

  // Warn tier: past the 95% band but inside the outer limits. Only where that band
  // means something on its own: an O/E chart's probability contour, or any funnel's
  // cross-sectional 95% line. Raw arrays, so multiply cannot move a point between
  // tiers; ghosted points are blanked as for sigmaSig. Mirrors api.py step 7c.
  const hasWarn = chart === 'oe' || chart === 'oep'
    || (funnel && ['p', 'pp', 'u', 'up'].includes(chart));
  const warnSig: boolean[] = hasWarn
    ? yCalc.map((v, i) => {
        if (excludeMask[i] || sigmaSig[i]) return false;
        return (!isNaN(ucl95Arr[i]) && v > ucl95Arr[i]) || (!isNaN(lcl95Arr[i]) && v < lcl95Arr[i]);
      })
    : [];

  // Detectability + per-point intervals (O/E charts only), computed from the RAW
  // arrays before multiply rescales them. For oep this uses oep's own wider limits:
  // the question is whether the point would flag on *this* chart.
  const isOe = chart === 'oe' || chart === 'oep';
  const detArr: number[] = [];
  const ciLoArr: number[] = [];
  const ciHiArr: number[] = [];
  if (isOe) {
    for (let i = 0; i < nPts; i++) {
      const e = nCalc ? nCalc[i] : NaN;
      detArr.push(oeDetectableRatio(uclArr[i] * e, e));
      const [lo, hi] = oePointCi(yCalc[i] * e, e);
      ciLoArr.push(lo);
      ciHiArr.push(hi);
    }
  }

  // The same question for a p/u funnel: what true proportion or rate a point would
  // have needed before its silence meant anything. Raw arrays; for pp/up the drawn,
  // over-dispersed limit, as oep uses its own. Mirrors _funnel_point_stats.
  const isFunnelPower = funnel && ['p', 'pp', 'u', 'up'].includes(chart);
  const fDetArr: number[] = [];
  if (isFunnelPower) {
    const binomial = chart === 'p' || chart === 'pp';
    for (let i = 0; i < nPts; i++) {
      const n = nCalc ? nCalc[i] : NaN;
      const t = uclArr[i] * n;
      const x = yCalc[i] * n;
      fDetArr.push(binomial ? binomialDetectableRate(t, n) : oeDetectableRatio(t, n));
      const [lo, hi] = binomial ? binomialPointCi(x, n) : oePointCi(x, n);
      ciLoArr.push(lo);
      ciHiArr.push(hi);
    }
  }
  const funnelPower = isFunnelPower
    ? funnelPowerSummary(chart, fDetArr, clArr.slice(), excludeMask)
    : {};

  // Multiply
  if (multiply !== 1.0) {
    for (let i = 0; i < nPts; i++) {
      clArr[i]   *= multiply;
      uclArr[i]  *= multiply;
      lclArr[i]  *= multiply;
      ucl95Arr[i] *= multiply;
      lcl95Arr[i] *= multiply;
      if (isOe) {
        // Every column on the y scale scales, same rule as the limits above.
        detArr[i]   *= multiply;
        ciLoArr[i]  *= multiply;
        ciHiArr[i]  *= multiply;
      }
      if (isFunnelPower) {
        fDetArr[i]  *= multiply;
        ciLoArr[i]  *= multiply;
        ciHiArr[i]  *= multiply;
      }
    }
  }

  const data = yCalc.map((v, i) => ({
    y: (chart === 't' ? Math.pow(Math.max(0, v), 3.6) : v) * multiply,
    cl: clArr[i],
    ucl: uclArr[i],
    lcl: lclArr[i],
    ucl_95: ucl95Arr[i],
    lcl_95: lcl95Arr[i],
    sigma_signal: sigmaSig[i],
    ...(hasWarn ? { warn_signal: warnSig[i] } : {}),
    runs_signal: runsSig[i],
    runs_signal_localized: runsLoc[i],
    ...(isOe ? {
      min_detectable_oe: detArr[i],
      ci_95_lower: ciLoArr[i],
      ci_95_upper: ciHiArr[i],
      // Counts, echoed back deliberately: funnel mode sorts by expected events, so
      // after the sort a caller cannot line their own inputs up against these rows.
      // Event counts, not ratios, so multiply does not touch them.
      observed: yCalc[i] * (nCalc ? nCalc[i] : NaN),
      expected: nCalc ? nCalc[i] : NaN,
    } : {}),
    ...(isFunnelPower ? {
      // Infinity (no count can flag) is not a value to plot or hover; the summary
      // keeps it, the column says "none".
      min_detectable: Number.isFinite(fDetArr[i]) ? fDetArr[i] : NaN,
      ci_95_lower: ciLoArr[i],
      ci_95_upper: ciHiArr[i],
    } : {}),
  }));

  // Runs rules assume temporal ordering; suppress them for cross-sectional funnel plots.
  if (funnel) {
    runsSig.fill(false);
    runsLoc.fill(false);
    for (const d of data) {
      d.runs_signal = false;
      d.runs_signal_localized = false;
    }
  }

  const signals = sigmaSig.some(s => s) || runsSig.some(s => s);
  const finalSummary = {
    ...summaries[summaries.length - 1],
    signals,
    n_obs: yCalc.filter(v => !isNaN(v)).length,
    ...(funnel ? { runs_disabled: true, note: 'runs signals suppressed (funnel mode)' } : {}),
    // Not folded into `signals`: at one false alarm in twenty per point, a funnel of
    // a few hundred providers would always report one.
    ...(hasWarn ? { n_warn: warnSig.filter(Boolean).length } : {}),
    // An unadjusted funnel whose providers spread wider than its null model allows:
    // its limits stay as they are, but a reader should know some signals may be that
    // spread, and that the adjustment is a stopgap [1, §5]. Mirrors api.py.
    ...(() => {
      const last = summaries[summaries.length - 1] ?? {};
      if (!last.overdispersed || 'dispersion_adjusted' in last) return {};
      const [call, basis, quantity] = DISPERSION_NOTE[chart];
      return {
        dispersion_note:
          `Providers vary more than ${basis} can explain: the estimated spread of ` +
          `true ${quantity} between them is τ = ${twoSig(last.dispersion_tau)}. ` +
          `Some signals here may reflect that spread (unmeasured case mix, data ` +
          `differences, or real variation in practice) rather than an individually ` +
          `unusual provider. Compare with ${call}, which judges each provider against ` +
          `that spread, and look for its cause: an adjustment is a temporary measure, ` +
          `not a fix.`,
      };
    })(),
    // How much signal the chart could carry, reported alongside what it found. A
    // funnel over small-volume providers mostly cannot detect anything, and the
    // honest reading of "no signal" there is "not enough data", not "fine".
    ...(isOe ? oePowerSummary(detArr, multiply, excludeMask) : {}),
    ...funnelPower,
  };

  return {
    chart_type: chart,
    method,
    signals,
    summary: finalSummary,
    data,
    connect,
    y_percent: yPercent,
    to_dict() {
      return {
        chart_type: this.chart_type,
        method: this.method,
        signals: this.signals,
        summary: this.summary,
        connect: this.connect,
        y_percent: this.y_percent,
        data: this.data.map(d => {
          const row: Record<string, unknown> = {
            ...d,
            cl:     isNaN(d.cl)     ? null : d.cl,
            ucl:    isNaN(d.ucl)    ? null : d.ucl,
            lcl:    isNaN(d.lcl)    ? null : d.lcl,
            ucl_95: isNaN(d.ucl_95) ? null : d.ucl_95,
            lcl_95: isNaN(d.lcl_95) ? null : d.lcl_95,
          };
          // Power columns (O/E charts and p/u funnels); absent elsewhere, so guard by presence.
          for (const col of ['min_detectable_oe', 'min_detectable', 'ci_95_lower', 'ci_95_upper']) {
            if (col in row && isNaN(row[col] as number)) row[col] = null;
          }
          return row;
        })
      };
    }
  };
}
