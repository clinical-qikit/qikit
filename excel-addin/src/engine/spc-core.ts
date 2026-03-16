import { ChartSpec, ChartType, SPCInput, SPCResult } from './spc-types';
import { nanmean, nanmedian, nansum, screenedMeanMR } from './spc-helpers';
import { A3, B3, B4, D2, D4 } from './constants';
import { detectSignals } from './signals';

export const CHARTS: Record<string, ChartSpec> = {
  run: {
    center: (yb) => nanmedian(yb),
    limits: (cl, y) => [new Array(y.length).fill(NaN), new Array(y.length).fill(NaN)],
    needsN: false, isAttribute: false, floorLcl: false
  },
  i: {
    center: (yb) => nanmean(yb),
    limits: (cl, y, n, mask) => {
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
    limits: (cl, y, n) => {
      const ucl = n!.map(ni => cl + 3 * Math.sqrt(cl * (1 - cl) / ni));
      const lcl = n!.map(ni => cl - 3 * Math.sqrt(cl * (1 - cl) / ni));
      return [ucl, lcl];
    },
    needsN: true, isAttribute: true, floorLcl: true
  },
  u: {
    center: (yb, nb) => nansum(yb.map((v, i) => v * nb![i])) / nansum(nb!),
    limits: (cl, y, n) => {
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
    center: (yb) => nanmean(yb),
    limits: (cl, y, n, mask, subN, sBar) => {
      const a3 = subN ? A3[subN] : NaN;
      return [new Array(y.length).fill(cl + a3 * sBar!), new Array(y.length).fill(cl - a3 * sBar!)];
    },
    needsN: false, isAttribute: false, floorLcl: false
  },
  s: {
    center: (yb) => nanmean(yb),
    limits: (cl, y, n, mask, subN) => {
      const b4 = subN ? B4[subN] : NaN;
      const b3 = subN ? B3[subN] : NaN;
      return [new Array(y.length).fill(b4 * cl), new Array(y.length).fill(b3 * cl)];
    },
    needsN: false, isAttribute: false, floorLcl: false
  }
};

export function compute(input: SPCInput): SPCResult {
  let { y, n, chart, method = 'anhoej', freeze, part, exclude = [], clOverride, multiply = 1.0, sBar, subgroupN } = input;
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
    const maskAgg = [];
    for (let i = 0; i < y.length; i += subgroupN) {
      const chunk = y.slice(i, i + subgroupN);
      if (chunk.length === 0) continue;
      
      if (chart === 'xbar') {
        yAgg.push(nanmean(chunk));
      } else {
        const m = nanmean(chunk);
        const sqDiffs = chunk.map(v => Math.pow(v - m, 2));
        yAgg.push(Math.sqrt(nansum(sqDiffs) / (chunk.length - 1)));
      }
      nAgg.push(chunk.length);
      maskAgg.push(mask[i]); 
    }
    yCalc = yAgg;
    nCalc = nAgg;
    y = [...yAgg];
    mask = [...maskAgg];
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
  const sigmaSig = new Array(nPts).fill(false);
  const runsSig = new Array(nPts).fill(false);
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
    const [uclSeg, lclSeg] = spec.limits(clVal, segY, segN, segMask, subgroupN, sBar);
    
    for (let j = 0; j < e - s; j++) {
      clArr[s + j] = clVal;
      uclArr[s + j] = uclSeg[j];
      lclArr[s + j] = spec.floorLcl ? Math.max(0, lclSeg[j]) : lclSeg[j];
    }

    // Signals per segment
    const { signals: sSig, summary: sSum } = detectSignals(segY, clArr.slice(s, e), method, uclArr.slice(s, e), lclArr.slice(s, e));
    for (let j = 0; j < e - s; j++) {
      runsSig[s + j] = sSig[j];
      sigmaSig[s + j] = (!isNaN(uclArr[s + j]) && segY[j] > uclArr[s + j]) || (!isNaN(lclArr[s + j]) && segY[j] < lclArr[s + j]);
    }
    summaries.push(sSum);
  }

  // Back-transform for t-chart
  if (chart === 't') {
    for (let i = 0; i < nPts; i++) {
      clArr[i] = Math.pow(Math.max(0, clArr[i]), 3.6);
      uclArr[i] = Math.pow(Math.max(0, uclArr[i]), 3.6);
      lclArr[i] = Math.pow(Math.max(0, lclArr[i]), 3.6);
    }
  }

  // Multiply
  if (multiply !== 1.0) {
    for (let i = 0; i < nPts; i++) {
      clArr[i] *= multiply;
      uclArr[i] *= multiply;
      lclArr[i] *= multiply;
    }
  }

  const data = yCalc.map((v, i) => ({
    y: (chart === 't' ? Math.pow(Math.max(0, v), 3.6) : v) * multiply,
    cl: clArr[i],
    ucl: uclArr[i],
    lcl: lclArr[i],
    sigma_signal: sigmaSig[i],
    runs_signal: runsSig[i]
  }));

  const signals = sigmaSig.some(s => s) || runsSig.some(s => s);
  const finalSummary = { ...summaries[summaries.length - 1], signals, n_obs: yCalc.filter(v => !isNaN(v)).length };

  return {
    chart_type: chart,
    method,
    signals,
    summary: finalSummary,
    data,
    to_dict() {
      return {
        chart_type: this.chart_type,
        method: this.method,
        signals: this.signals,
        summary: this.summary,
        data: this.data.map(d => ({
          ...d,
          cl: isNaN(d.cl) ? null : d.cl,
          ucl: isNaN(d.ucl) ? null : d.ucl,
          lcl: isNaN(d.lcl) ? null : d.lcl
        }))
      };
    }
  };
}
