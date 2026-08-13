import { ChartSpec, LimitMethod, SPCInput, SPCResult } from './spc-types';
import { nanmean, nanmedian, nansum, screenedMeanMR } from './spc-helpers';
import { D2, D4, Z_95, Z_998, a3, b3, b4, c4 } from './constants';
import { EXACT_MAX_LAMBDA, byarQuantile, poissonQuantileInterp } from './stats';
import { detectSignals } from './signals';

/**
 * Funnel limits for an O/E chart at one probability contour, on the O/E scale.
 *
 * With Eᵢ expected events and θ₀ the center line, the count of observed events is
 * modelled Poisson(λᵢ = θ₀·Eᵢ); the limit is that distribution's quantile divided
 * back through Eᵢ. Dividing by Eᵢ is what makes the funnel narrow as volume grows
 * while the underlying count distribution widens.
 *
 * Unlike the p/u charts these limits are asymmetric about the center line, which is
 * the whole point at low volume: a physician with 3 expected deaths has a very
 * different amount of room above the line than below it, and the normal
 * approximation would give them the same and then clip the lower limit at zero.
 *
 * Mirrors _oe_limit_pair in src/qikit/spc/limits.py.
 */
function oeLimitPair(
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
 * Winsorized multiplicative over-dispersion factor φ̂. Spiegelhalter, Quality &
 * Safety in Health Care 2005;14:347-351. Mirrors oe_dispersion_phi in limits.py.
 *
 * Across a few hundred providers, exact Poisson limits routinely flag far more than
 * the nominal 0.2%: real providers differ for reasons the risk model does not
 * capture. φ̂ measures that excess and widens the limits by √φ̂.
 *
 * Residuals use the Poisson variance-stabilising transform z = 2(√O − √(θ₀E)),
 * much closer to standard normal at small expected counts than the Pearson residual;
 * winsorizing at the 10th/90th percentiles stops the outliers being screened for from
 * inflating the estimate past themselves. Returns 1.0 when φ̂ is within two standard
 * errors of 1 under the null, so the adjustment only ever widens.
 *
 * Caveat on small cohorts: the pooled ΣO/ΣE center line is not itself robust, so
 * across a dozen providers one extreme performer drags that line toward itself and
 * inflates φ̂ even after its own residual is clipped. clOverride anchors the center
 * line and removes the effect; with a few hundred providers it is negligible.
 */
export function oeDispersionPhi(
  cl: number, y: number[], n: number[] | undefined, mask: boolean[]
): number {
  if (!n) throw new Error('Over-dispersion adjustment requires expected events (n).');

  const z: number[] = [];
  for (let i = 0; i < y.length; i++) {
    if (!mask[i]) continue;
    const observed = y[i] * n[i]; // y arrives as the O/E ratio
    const zi = 2 * (Math.sqrt(observed) - Math.sqrt(cl * n[i]));
    if (Number.isFinite(zi)) z.push(zi);
  }

  const k = z.length;
  if (k < 2) return 1.0;

  const sorted = [...z].sort((a, b) => a - b);
  const lo = percentile(sorted, 10);
  const hi = percentile(sorted, 90);

  let total = 0;
  for (const zi of z) {
    const w = Math.min(hi, Math.max(lo, zi));
    total += w * w;
  }
  const phi = total / k;

  return phi > 1 + 2 * Math.sqrt(2 / k) ? phi : 1.0;
}

/**
 * Over-dispersed O/E limits: θ₀ ± z·√(φ̂·θ₀/Eᵢ).
 *
 * Necessarily a normal approximation — a multiplicative variance factor has no
 * counterpart in an exact Poisson quantile, so the two do not compose. Same trade the
 * Laney p′/u′ charts make.
 */
function oepLimitPair(
  cl: number, n: number[] | undefined, phi: number, z: number
): [number[], number[]] {
  const ucl: number[] = [];
  const lcl: number[] = [];
  for (const ni of n ?? []) {
    const e = ni > 0 ? ni : NaN;
    const half = z * Math.sqrt((phi * cl) / e);
    ucl.push(cl + half);
    lcl.push(cl - half);
  }
  return [ucl, lcl];
}

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
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, limitMethod) =>
      oeLimitPair(cl, n, 0.001, 0.999, Z_998, limitMethod ?? 'exact'),
    limits95: (cl, _y, n, _mask, _subN, _sBar, _sigmaHat, limitMethod) =>
      oeLimitPair(cl, n, 0.025, 0.975, Z_95, limitMethod ?? 'exact'),
    needsN: true, isAttribute: true, floorLcl: true
  },
  oep: {
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, y, n, mask) =>
      oepLimitPair(cl, n, oeDispersionPhi(cl, y, n, mask), Z_998),
    limits95: (cl, y, n, mask) =>
      oepLimitPair(cl, n, oeDispersionPhi(cl, y, n, mask), Z_95),
    needsN: true, isAttribute: true, floorLcl: true
  }
};

export function compute(input: SPCInput): SPCResult {
  let { y, n, chart, method = 'anhoej', freeze, part, exclude = [], clOverride, multiply = 1.0, sBar, sigmaHat, subgroupN, funnel = false } = input;

  if (input.limitMethod !== undefined && chart === 'oep') {
    throw new Error(
      'limitMethod is not available for chart "oep". A multiplicative over-dispersion ' +
      'factor has no counterpart in an exact Poisson quantile, so the adjusted limits ' +
      'are always a normal approximation. Use chart "oe" for exact or Byar limits ' +
      'without the over-dispersion adjustment.'
    );
  }
  if (input.limitMethod !== undefined && chart !== 'oe') {
    throw new Error(
      `limitMethod is only valid for chart "oe". Got chart "${chart}". ` +
      `Other charts use 3σ limits, which have no quantile method to choose.`
    );
  }
  const limitMethod: LimitMethod = input.limitMethod ?? 'exact';
  if (chart === 'oe' && limitMethod !== 'exact' && limitMethod !== 'byar') {
    throw new Error(`limitMethod must be "exact" or "byar", got "${limitMethod}".`);
  }

  // Resolved display hints (mirrors Python qic() semantics)
  const yPercent = input.yPercent ?? (chart === 'p' || chart === 'pp');
  const connect = funnel ? false : (input.connect ?? null);
  const spec = CHARTS[chart === 't' ? 'i' : chart];

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
    
    // Limits
    // Important: for t-chart, we need to pass clVal which is in transformed space
    const [uclSeg, lclSeg, clSeg] = spec.limits(clVal, segY, segN, segMask, subgroupN, sBar, sigmaHat, limitMethod);

    // A chart whose limits come from a distribution supplies its own 95% band; the
    // 2/3-of-3σ shortcut below holds only for symmetric, normal limits.
    const band95 = spec.limits95
      ? spec.limits95(clVal, segY, segN, segMask, subgroupN, sBar, sigmaHat, limitMethod)
      : undefined;

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
    summaries.push(sSum);
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

  // Multiply
  if (multiply !== 1.0) {
    for (let i = 0; i < nPts; i++) {
      clArr[i]   *= multiply;
      uclArr[i]  *= multiply;
      lclArr[i]  *= multiply;
      ucl95Arr[i] *= multiply;
      lcl95Arr[i] *= multiply;
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
    runs_signal: runsSig[i],
    runs_signal_localized: runsLoc[i]
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
    // Which quantile method drew the limits is not recoverable from the numbers
    // alone, and an O/E funnel is the kind of chart that ends up in a credentialing
    // file. Record it.
    ...(chart === 'oe' ? { limit_method: limitMethod } : {}),
    // Whether the over-dispersion adjustment actually engaged, and by how much, is
    // the first thing a reviewer asks of one of these charts. φ̂ = 1.0 means the
    // sample was within noise of Poisson and the limits were left alone.
    ...(chart === 'oep'
      ? (() => {
          const phi = oeDispersionPhi(clArr[0], yCalc, nCalc, mask);
          return { dispersion_phi: phi, dispersion_adjusted: phi > 1.0 };
        })()
      : {}),
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
        data: this.data.map(d => ({
          ...d,
          cl:     isNaN(d.cl)     ? null : d.cl,
          ucl:    isNaN(d.ucl)    ? null : d.ucl,
          lcl:    isNaN(d.lcl)    ? null : d.lcl,
          ucl_95: isNaN(d.ucl_95) ? null : d.ucl_95,
          lcl_95: isNaN(d.lcl_95) ? null : d.lcl_95,
        }))
      };
    }
  };
}
