import { describe, test, expect } from 'vitest';
import { compute } from '../src';

// The Provost & Murray screen drops moving ranges above D4·MR̄. Where most MRs
// are zero the threshold falls below the one MR that carries the variation, so
// screening removed it and the survivors averaged to 0 — collapsing UCL/LCL
// onto CL and flagging every point. Mirrors src/qikit/spc/limits.py.
describe('sigma estimation does not collapse under screening', () => {
  test('a lone outlier on a flat run is the only point flagged', () => {
    const y = [...new Array(29).fill(10), 40];
    const { data } = compute({ y, chart: 'i' });
    const cl = data[0].cl;

    expect(data[0].ucl).toBeGreaterThan(cl);
    expect(data[0].lcl).toBeLessThan(cl);
    // σ̂ falls back to the unscreened MR̄ = 30/29 → σ̂ = 0.9171
    expect(data[0].ucl).toBeCloseTo(cl + (3 * (30 / 29)) / 1.128, 6);

    const flagged = data.filter(d => d.sigma_signal);
    expect(flagged).toHaveLength(1);
    expect(data[29].sigma_signal).toBe(true);
  });

  test('a perfectly flat series reports no limits rather than zero-width ones', () => {
    const { data } = compute({ y: new Array(20).fill(10), chart: 'i' });
    expect(data.every(d => Number.isNaN(d.ucl))).toBe(true);
    expect(data.every(d => Number.isNaN(d.lcl))).toBe(true);
    expect(data.some(d => d.sigma_signal)).toBe(false);
  });

  test('ordinary screening is untouched — a lone spike stays out of the limits', () => {
    const y = [10, 11, 9, 10, 12, 10, 11, 9, 10, 12, 90, 10, 11, 9, 10, 12];
    const { data } = compute({ y, chart: 'i' });
    expect(data[0].ucl).toBeLessThan(90);
  });

  test('ip shares the same limits path', () => {
    const y = [...new Array(29).fill(10), 40];
    const { data } = compute({ y, n: new Array(30).fill(100), chart: 'ip' });
    expect(data.filter(d => d.sigma_signal)).toHaveLength(1);
  });
});
