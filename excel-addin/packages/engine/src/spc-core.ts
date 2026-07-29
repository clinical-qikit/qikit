import { ChartSpec, SPCInput, SPCResult } from './spc-types';
import { nanmean, nanmedian, nansum, screenedMeanMR } from './spc-helpers';
import { D2, D4, a3, b3, b4, c4 } from './constants';
import { detectSignals } from './signals';

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

export const CHARTS: Record<string, ChartSpec> = {
  run: {
    center: (yb) => nanmedian(yb),
    limits: (_cl, y) => [new Array(y.length).fill(NaN), new Array(y.length).fill(NaN)],
    needsN: false, isAttribute: false, floorLcl: false
  },
  i: {
    center: (yb) => nanmean(yb),
    limits: (cl, y, _n, mask) => {
      const mrBar = screenedMeanMR(y, mask);
      const sigma = mrBar / D2[2];
      return [new Array(y.length).fill(cl + 3 * sigma), new Array(y.length).fill(cl - 3 * sigma)];
    },
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
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, y, n, mask) => {
      const sigmaBase = n!.map(ni => Math.sqrt(cl * (1 - cl) / ni));
      const z = y.map((v, i) => (v - cl) / sigmaBase[i]);
      const zValid = z.filter((v, i) => mask[i] && !isNaN(v));
      let sigmaZ = 1.0;
      if (zValid.length > 1) {
        const mrs = [];
        for (let i = 1; i < zValid.length; i++) mrs.push(Math.abs(zValid[i] - zValid[i - 1]));
        sigmaZ = nanmean(mrs) / D2[2];
      }
      return [sigmaBase.map(s => cl + 3 * s * sigmaZ), sigmaBase.map(s => cl - 3 * s * sigmaZ)];
    },
    needsN: true, isAttribute: true, floorLcl: true
  },
  up: {
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, y, n, mask) => {
      const sigmaBase = n!.map(ni => Math.sqrt(cl / ni));
      const z = y.map((v, i) => (v - cl) / sigmaBase[i]);
      const zValid = z.filter((v, i) => mask[i] && !isNaN(v));
      let sigmaZ = 1.0;
      if (zValid.length > 1) {
        const mrs = [];
        for (let i = 1; i < zValid.length; i++) mrs.push(Math.abs(zValid[i] - zValid[i - 1]));
        sigmaZ = nanmean(mrs) / D2[2];
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
    // UCL = B4(nᵢ)·S̄, LCL = B3(nᵢ)·S̄. Montgomery (2019), §6.4.
    // Unequal sizes use the pooled σ̂ form σ̂·(c4(nᵢ) ± 3√(1 − c4(nᵢ)²)).
    // Known approximation: strictly the center line is c4(nᵢ)·σ̂ and varies per
    // subgroup too, but ChartSpec center lines are scalar, so the CL stays flat.
    center: (yb) => nanmean(yb),
    limits: (cl, y, n, _mask, subN, _sBar, sigmaHat) => {
      const sizes = subgroupSizes(n, subN, y.length);
      if (sigmaHat !== undefined) {
        const spread = sizes.map(ni => 3 * Math.sqrt(Math.max(0, 1 - c4(ni) * c4(ni))));
        return [
          sizes.map((ni, i) => sigmaHat * (c4(ni) + spread[i])),
          sizes.map((ni, i) => Math.max(0, sigmaHat * (c4(ni) - spread[i]))),
        ];
      }
      return [sizes.map(ni => b4(ni) * cl), sizes.map(ni => b3(ni) * cl)];
    },
    needsN: false, isAttribute: false, floorLcl: false
  },
  ip: {
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, y, _n, mask) => {
      const mrBar = screenedMeanMR(y, mask);
      const sigma = mrBar / D2[2];
      return [new Array(y.length).fill(cl + 3 * sigma), new Array(y.length).fill(cl - 3 * sigma)];
    },
    needsN: true, isAttribute: true, floorLcl: false
  }
};

export function compute(input: SPCInput): SPCResult {
  let { y, n, chart, method = 'anhoej', freeze, part, exclude = [], clOverride, multiply = 1.0, sBar, sigmaHat, subgroupN, funnel = false } = input;

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
    if (!['p', 'pp', 'u', 'up'].includes(chart)) {
      throw new Error(`funnel=true is only valid for attribute charts with denominators (p, pp, u, up). Got chart "${chart}".`);
    }
    if (!nCalc) {
      throw new Error('funnel=true requires denominators (n).');
    }
    const order = nCalc.map((_, i) => i).sort((a, b) => nCalc![a] - nCalc![b]);
    y = order.map(i => (y as number[])[i]);
    yCalc = order.map(i => yCalc[i]);
    nCalc = order.map(i => nCalc![i]);
  }

  let mask = new Array(y.length).fill(true);
  const excludeArr = Array.isArray(exclude) ? exclude : [exclude];
  const partArr = part ? (Array.isArray(part) ? part : [part]) : undefined;
  excludeArr.forEach(i => mask[i - 1] = false);
  if (freeze) {
    for (let i = freeze; i < y.length; i++) mask[i] = false;
  }

  // Handle xbar/s aggregation (subgrouping)
  if ((chart === 'xbar' || chart === 's') && subgroupN) {
    const yAgg = [];
    const nAgg = [];
    const sdAgg = [];
    const maskAgg = [];
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
    }
    yCalc = yAgg;
    nCalc = nAgg;
    y = [...yAgg];
    mask = [...maskAgg];

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
    const [uclSeg, lclSeg] = spec.limits(clVal, segY, segN, segMask, subgroupN, sBar, sigmaHat);
    
    for (let j = 0; j < e - s; j++) {
      clArr[s + j] = clVal;
      uclArr[s + j] = uclSeg[j];
      lclArr[s + j] = spec.floorLcl ? Math.max(0, lclSeg[j]) : lclSeg[j];
      const spread = uclSeg[j] - clVal;
      ucl95Arr[s + j] = clVal + spread * (2 / 3);
      const l95 = clVal - spread * (2 / 3);
      lcl95Arr[s + j] = spec.floorLcl ? Math.max(0, l95) : l95;
    }

    // Signals per segment
    const { signals: sSig, signalsLocalized: sLoc, summary: sSum } = detectSignals(segY, clArr.slice(s, e), method, uclArr.slice(s, e), lclArr.slice(s, e));
    for (let j = 0; j < e - s; j++) {
      runsSig[s + j] = sSig[j];
      runsLoc[s + j] = sLoc[j];
      sigmaSig[s + j] = (!isNaN(uclArr[s + j]) && segY[j] > uclArr[s + j]) || (!isNaN(lclArr[s + j]) && segY[j] < lclArr[s + j]);
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
