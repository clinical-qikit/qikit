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

export function screenedMeanMR(y: number[], mask: boolean[]): number {
  const yValid: number[] = [];
  for (let i = 0; i < y.length; i++) {
    if (mask[i] && typeof y[i] === 'number' && !isNaN(y[i])) {
      yValid.push(y[i]);
    }
  }
  if (yValid.length < 2) return NaN;
  
  const mrs = movingRanges(yValid);
  const mrBar = nanmean(mrs);
  const screened = mrs.filter(m => m <= D4[2] * mrBar);
  return screened.length > 0 ? nanmean(screened) : mrBar;
}

/**
 * Binomial coefficient nCr.
 */
export function binomCoeff(n: number, k: number): number {
  if (k < 0 || k > n) return 0;
  if (k === 0 || k === n) return 1;
  if (k > n / 2) k = n - k;
  
  let res = 1;
  for (let i = 1; i <= k; i++) {
    res = res * (n - i + 1) / i;
  }
  return Math.round(res);
}
