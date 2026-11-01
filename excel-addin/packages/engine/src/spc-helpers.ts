import { D4 } from './constants';

export function nanmean(arr: number[]): number {
  const valid = arr.filter(v => typeof v === 'number' && !isNaN(v));
  if (valid.length === 0) return NaN;
  return valid.reduce((a, b) => a + b, 0) / valid.length;
}

export function nanmedian(arr: number[]): number {
  const valid = arr.filter(v => typeof v === 'number' && !isNaN(v)).sort((a, b) => a - b);
  if (valid.length === 0) return NaN;
  const mid = Math.floor(valid.length / 2);
  return valid.length % 2 !== 0 ? valid[mid] : (valid[mid - 1] + valid[mid]) / 2;
}

export function nansum(arr: number[]): number {
  const valid = arr.filter(v => typeof v === 'number' && !isNaN(v));
  return valid.reduce((a, b) => a + b, 0);
}

export function movingRanges(y: number[]): number[] {
  const mrs: number[] = [];
  for (let i = 1; i < y.length; i++) {
    mrs.push(Math.abs(y[i] - y[i - 1]));
  }
  return mrs;
}

/**
 * Mean moving range of the baseline, screened once as qicharts2 does (Nelson 1982):
 * ranges at or above 3.267·MR̄ are dropped and MR̄ recomputed. A missing value breaks
 * the series rather than bridging it. Where the screen would leave MR̄ = 0 (most ranges
 * zero), the unscreened MR̄ is kept. Twin of screened_mean_mr in shewhart.py.
 */
export function screenedMeanMR(y: number[], mask: boolean[]): number {
  const base: number[] = [];
  for (let i = 0; i < y.length; i++) if (mask[i]) base.push(y[i]);
  const mrs = movingRanges(base).filter(m => !isNaN(m));
  if (mrs.length === 0) return NaN;
  const mrBar = mrs.reduce((a, b) => a + b, 0) / mrs.length;
  const kept = mrs.filter(m => m < D4[2] * mrBar);
  const screened = kept.length ? kept.reduce((a, b) => a + b, 0) / kept.length : NaN;
  return screened > 0 ? screened : mrBar;
}
