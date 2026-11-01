import { SignalMethod } from './spc-types';

/**
 * Longest run expected by chance among n useful points: round(log2 n) + 3, as qicharts2
 * computes it (Anhoej & Olesen 2014). A run longer than this signals. Twin of
 * longest_run_max in rules.py.
 */
export function longestRunMax(n: number): number {
  return n > 0 ? Math.round(Math.log2(n)) + 3 : 0;
}

/**
 * Fewest crossings expected by chance: R's qbinom(0.05, n − 1, 0.5), the smallest k with
 * P(X ≤ k) ≥ 0.05. Fewer crossings than this signal. Twin of n_crossings_min in rules.py.
 * Accumulated in log space: the binomial coefficient overflows past n ≈ 1,030.
 */
export function nCrossingsMin(n: number): number {
  const trials = Math.max(n - 1, 0);
  let logPmf = -trials * Math.LN2; // k = 0
  let cdf = 0;
  for (let k = 0; k <= trials; k++) {
    if (k > 0) logPmf += Math.log((trials - k + 1) / k);
    cdf += Math.exp(logPmf);
    if (cdf >= 0.05) return k;
  }
  return trials;
}

export function countCrossings(y: number[], cl: number[]): number {
  const sides: boolean[] = [];
  for (let i = 0; i < y.length; i++) {
    if (isNaN(y[i]) || y[i] === cl[i]) continue;
    sides.push(y[i] > cl[i]);
  }
  let crossings = 0;
  for (let i = 1; i < sides.length; i++) {
    if (sides[i] !== sides[i - 1]) crossings++;
  }
  return crossings;
}

export function longestRun(y: number[], cl: number[]): number {
  let maxRun = 0;
  let current = 0;
  let lastSide: boolean | null = null;
  for (let i = 0; i < y.length; i++) {
    if (isNaN(y[i]) || y[i] === cl[i]) continue;
    const side = y[i] > cl[i];
    if (side === lastSide) {
      current++;
    } else {
      current = 1;
      lastSide = side;
    }
    maxRun = Math.max(maxRun, current);
  }
  return maxRun;
}

export function markLongRuns(y: number[], cl: number[], threshold: number): boolean[] {
  const signals = new Array(y.length).fill(false);
  const useful: { idx: number; side: boolean }[] = [];
  for (let i = 0; i < y.length; i++) {
    if (!isNaN(y[i]) && y[i] !== cl[i]) {
      useful.push({ idx: i, side: y[i] > cl[i] });
    }
  }

  if (useful.length === 0) return signals;

  let runStart = 0;
  for (let j = 1; j <= useful.length; j++) {
    if (j === useful.length || useful[j].side !== useful[runStart].side) {
      const runLen = j - runStart;
      if (runLen >= threshold) {
        for (let k = runStart; k < j; k++) {
          signals[useful[k].idx] = true;
        }
      }
      runStart = j;
    }
  }
  return signals;
}

export function markTrends(y: number[], threshold: number): boolean[] {
  const signals = new Array(y.length).fill(false);
  const useful: { idx: number; val: number }[] = [];
  for (let i = 0; i < y.length; i++) {
    if (!isNaN(y[i])) {
      useful.push({ idx: i, val: y[i] });
    }
  }

  if (useful.length < threshold) return signals;

  for (let j = 0; j < useful.length; j++) {
    if (j >= threshold - 1) {
      // Increasing
      let isInc = true;
      for (let k = j - threshold + 1; k < j; k++) {
        if (useful[k].val >= useful[k + 1].val) {
          isInc = false;
          break;
        }
      }
      if (isInc) {
        for (let k = j - threshold + 1; k <= j; k++) {
          signals[useful[k].idx] = true;
        }
      }

      // Decreasing
      let isDec = true;
      for (let k = j - threshold + 1; k < j; k++) {
        if (useful[k].val <= useful[k + 1].val) {
          isDec = false;
          break;
        }
      }
      if (isDec) {
        for (let k = j - threshold + 1; k <= j; k++) {
          signals[useful[k].idx] = true;
        }
      }
    }
  }
  return signals;
}

export function markOscillation(y: number[], threshold: number): boolean[] {
  const signals = new Array(y.length).fill(false);
  const useful: number[] = [];
  for (let i = 0; i < y.length; i++) {
    if (!isNaN(y[i])) useful.push(i);
  }

  if (useful.length < threshold) return signals;

  for (let i = 0; i <= useful.length - threshold; i++) {
    const chunk = useful.slice(i, i + threshold);
    let allAlternate = true;
    let lastSign = 0;
    for (let j = 0; j < chunk.length - 1; j++) {
      const diff = y[chunk[j + 1]] - y[chunk[j]];
      if (diff === 0) {
        allAlternate = false;
        break;
      }
      const sign = Math.sign(diff);
      if (j > 0 && sign === lastSign) {
        allAlternate = false;
        break;
      }
      lastSign = sign;
    }
    if (allAlternate) {
      for (const idx of chunk) signals[idx] = true;
    }
  }
  return signals;
}

export function markZones(
  y: number[], cl: number[], ucl: number[],
  nBeyond: number, window: number, sigmaMult: number
): boolean[] {
  const signals = new Array(y.length).fill(false);
  const sigma = ucl.map((u, i) => (u - cl[i]) / 3);

  const upperBeyond = y.map((v, i) => !isNaN(sigma[i]) && sigma[i] > 0 && v > cl[i] + sigmaMult * sigma[i]);
  const lowerBeyond = y.map((v, i) => !isNaN(sigma[i]) && sigma[i] > 0 && v < cl[i] - sigmaMult * sigma[i]);

  for (let i = window - 1; i < y.length; i++) {
    let uCount = 0;
    let lCount = 0;
    for (let j = i - window + 1; j <= i; j++) {
      if (upperBeyond[j]) uCount++;
      if (lowerBeyond[j]) lCount++;
    }
    if (uCount >= nBeyond) {
      for (let j = i - window + 1; j <= i; j++) if (upperBeyond[j]) signals[j] = true;
    }
    if (lCount >= nBeyond) {
      for (let j = i - window + 1; j <= i; j++) if (lowerBeyond[j]) signals[j] = true;
    }
  }
  return signals;
}

export function markStratification(y: number[], cl: number[], ucl: number[], threshold: number): boolean[] {
  const signals = new Array(y.length).fill(false);
  const sigma = ucl.map((u, i) => (u - cl[i]) / 3);
  const within1s = y.map((v, i) => v > cl[i] - sigma[i] && v < cl[i] + sigma[i]);

  let count = 0;
  for (let i = 0; i < y.length; i++) {
    if (within1s[i]) count++; else count = 0;
    if (count >= threshold) {
      for (let j = i - threshold + 1; j <= i; j++) signals[j] = true;
    }
  }
  return signals;
}

export function markMixture(y: number[], cl: number[], ucl: number[], threshold: number): boolean[] {
  const signals = new Array(y.length).fill(false);
  const sigma = ucl.map((u, i) => (u - cl[i]) / 3);
  const outside1s = y.map((v, i) => v > cl[i] + sigma[i] || v < cl[i] - sigma[i]);

  let count = 0;
  for (let i = 0; i < y.length; i++) {
    if (outside1s[i]) count++; else count = 0;
    if (count >= threshold) {
      for (let j = i - threshold + 1; j <= i; j++) signals[j] = true;
    }
  }
  return signals;
}

export function detectSignals(
  y: number[], cl: number[], method: SignalMethod,
  ucl: number[], lcl: number[]
): { signals: boolean[]; signalsLocalized: boolean[]; summary: Record<string, any> } {
  const nUseful = y.filter((v, i) => !isNaN(v) && v !== cl[i]).length;
  let signalArr = new Array(y.length).fill(false);
  // Same as signalArr but excluding any whole-series pattern — see the anhoej
  // branch. Identical to signalArr for every other method.
  let localizedArr = new Array(y.length).fill(false);
  let summary: Record<string, any> = { n_useful: nUseful };

  if (method === 'anhoej') {
    const longest = longestRun(y, cl);
    const crossings = countCrossings(y, cl);
    const runMax = longestRunMax(nUseful);
    const crossMin = nCrossingsMin(nUseful);

    const runSignal = nUseful > 0 && longest > runMax;
    const crossSignal = nUseful > 0 && crossings < crossMin;

    // Localized pattern — only the points forming the long runs
    localizedArr = runSignal ? markLongRuns(y, cl, runMax + 1) : new Array(y.length).fill(false);
    signalArr = localizedArr.slice();
    if (crossSignal) {
      // Whole-series pattern — mark all useful points. Long-run marks are a
      // subset of the useful points, so this is a superset of localizedArr.
      for (let i = 0; i < y.length; i++) if (!isNaN(y[i]) && y[i] !== cl[i]) signalArr[i] = true;
    }
    summary = {
      ...summary,
      longest_run: longest,
      longest_run_max: runMax,
      n_crossings: crossings,
      n_crossings_min: crossMin,
      longest_run_signal: runSignal,
      crossings_signal: crossSignal,
      runs_signal: runSignal || crossSignal,
    };
  } else if (method === 'ihi') {
    // Provost & Murray: on a run chart a shift of 6 and a trend of 5; on a Shewhart chart
    // a shift of 8, a trend of 6, 2 of 3 beyond 2σ and 15 within 1σ. A repeated value is
    // passed over in a trend. Twin of _ihi in rules.py.
    const hasLimits = ucl.some(v => !isNaN(v));
    const shiftArr = markLongRuns(y, cl, hasLimits ? 8 : 6);
    const trendArr = markTrends(dropTies(y), hasLimits ? 6 : 5);
    const zoneArr = hasLimits ? markZones(y, cl, ucl, 2, 3, 2) : new Array(y.length).fill(false);
    const innerArr = hasLimits ? markStratification(y, cl, ucl, 15) : new Array(y.length).fill(false);
    signalArr = shiftArr.map((s, i) => s || trendArr[i] || zoneArr[i] || innerArr[i]);
    localizedArr = signalArr.slice();
    summary = {
      ...summary,
      shift_signal: shiftArr.some(s => s),
      trend_signal: trendArr.some(s => s),
      runs_signal: signalArr.some(s => s),
    };
  } else if (method === 'weco') {
    // A point beyond the limits is the chart's own test (sigma_signal), not a runs rule.
    const r1 = y.map((v, i) => (!isNaN(ucl[i]) && v > ucl[i]) || (!isNaN(lcl[i]) && v < lcl[i]));
    const r2 = markZones(y, cl, ucl, 2, 3, 2);
    const r3 = markZones(y, cl, ucl, 4, 5, 1);
    const r4 = markLongRuns(y, cl, 8);
    signalArr = r2.map((v, i) => v || r3[i] || r4[i]);
    localizedArr = signalArr.slice();
    summary.weco_rules_triggered = [
      r1.some(v => v) ? 1 : null,
      r2.some(v => v) ? 2 : null,
      r3.some(v => v) ? 3 : null,
      r4.some(v => v) ? 4 : null,
    ].filter(v => v !== null);
  } else if (method === 'nelson') {
    const r1 = y.map((v, i) => (!isNaN(ucl[i]) && v > ucl[i]) || (!isNaN(lcl[i]) && v < lcl[i]));
    const r2 = markLongRuns(y, cl, 9);
    const r3 = markTrends(y, 6);
    const r4 = markOscillation(y, 14);
    const r5 = markZones(y, cl, ucl, 2, 3, 2);
    const r6 = markZones(y, cl, ucl, 4, 5, 1);
    const r7 = markStratification(y, cl, ucl, 15);
    const r8 = markMixture(y, cl, ucl, 8);
    signalArr = r2.map((v, i) => v || r3[i] || r4[i] || r5[i] || r6[i] || r7[i] || r8[i]);
    localizedArr = signalArr.slice();
    summary.nelson_rules_triggered = [
      r1.some(v => v) ? 1 : null,
      r2.some(v => v) ? 2 : null,
      r3.some(v => v) ? 3 : null,
      r4.some(v => v) ? 4 : null,
      r5.some(v => v) ? 5 : null,
      r6.some(v => v) ? 6 : null,
      r7.some(v => v) ? 7 : null,
      r8.some(v => v) ? 8 : null,
    ].filter(v => v !== null);
  }

  return { signals: signalArr, signalsLocalized: localizedArr, summary };
}

/** y with a repeated value blanked (NaN), so a trend passes over ties (Provost & Murray). */
function dropTies(y: number[]): number[] {
  const out = y.slice();
  let last = NaN;
  for (let i = 0; i < out.length; i++) {
    if (isNaN(out[i])) continue;
    if (out[i] === last) out[i] = NaN;
    else last = out[i];
  }
  return out;
}
