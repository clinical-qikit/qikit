import { describe, test, expect } from 'vitest';
import { compute } from '../src';
import { binomialDetectableRate, binomialPointCi } from '../src/spc-core';
import { binomialCdf, binomialQuantiles, binomialThetaForCdf } from '../src/stats';

// Twin of TestBinomialInversion / TestBinomialPointCI / TestBinomialDetectability /
// TestFunnelPowerReporting in tests/test_spc.py. The shared fixtures prove the column
// values match Python; these cover the anchors and edge paths a fixture cannot express.

function directCdf(k: number, m: number, t: number): number {
  let c = 0;
  let comb = 1;
  for (let j = 0; j <= k; j++) {
    if (j > 0) comb = comb * (m - j + 1) / j;
    c += comb * Math.pow(t, j) * Math.pow(1 - t, m - j);
  }
  return c;
}

const Y = [4, 1, 3, 2, 4, 3, 5, 6, 8, 7, 10, 12, 19, 48];
const N = [12, 15, 20, 24, 30, 38, 45, 60, 75, 90, 120, 150, 200, 260];

describe('binomialCdf', () => {
  test('matches a direct sum', () => {
    for (const [k, m, t] of [[3, 20, 0.1], [0, 5, 0.3], [10, 40, 0.2], [50, 300, 0.15]]) {
      expect(binomialCdf(k, m, t)).toBeCloseTo(directCdf(k, m, t), 12);
    }
  });

  test('survives hospital volumes', () => {
    expect(binomialCdf(5000, 10_000, 0.5)).toBeCloseTo(0.5040, 4);
  });

  test('edges', () => {
    expect(binomialCdf(-1, 10, 0.3)).toBe(0.0);
    expect(binomialCdf(10, 10, 0.3)).toBe(1.0);
    expect(binomialCdf(3, 10, 0.0)).toBe(1.0);
    expect(binomialCdf(3, 10, 1.0)).toBe(0.0);
    expect(Number.isNaN(binomialCdf(3, 10, NaN))).toBe(true);
  });
});

describe('binomialThetaForCdf', () => {
  test('inverts the CDF', () => {
    for (const [k, m] of [[0, 1], [0, 12], [3, 20], [46, 260], [900, 10_000]]) {
      for (const p of [0.025, 0.2, 0.975]) {
        expect(binomialCdf(k, m, binomialThetaForCdf(k, m, p))).toBeCloseTo(p, 12);
      }
    }
  });

  test('NaN where no θ moves the CDF', () => {
    expect(Number.isNaN(binomialThetaForCdf(10, 10, 0.5))).toBe(true);
    expect(Number.isNaN(binomialThetaForCdf(-1, 10, 0.5))).toBe(true);
  });
});

describe('binomialPointCi', () => {
  test('Clopper–Pearson anchors', () => {
    const [lo, hi] = binomialPointCi(10, 100);
    expect(lo).toBeCloseTo(0.0490, 4);
    expect(hi).toBeCloseTo(0.1762, 4);
    const [lo0, hi0] = binomialPointCi(0, 20);
    expect(lo0).toBe(0.0);
    expect(hi0).toBeCloseTo(1 - Math.pow(0.025, 1 / 20), 12);
    expect(binomialPointCi(20, 20)[1]).toBe(1.0);
  });

  test('NaN without an exact statement', () => {
    expect(binomialPointCi(3, 0)).toEqual([NaN, NaN]);
    expect(binomialPointCi(3, 10.5)).toEqual([NaN, NaN]);
    expect(binomialPointCi(2.5, 10)).toEqual([NaN, NaN]);
  });
});

describe('binomialDetectableRate', () => {
  test('achieves exactly 80% power', () => {
    for (const n of [10, 30, 100, 400, 1000]) {
      const [[, t]] = binomialQuantiles([0.001, 0.999], n, 0.1, [-3.09, 3.09]);
      const theta = binomialDetectableRate(t, n);
      expect(1 - directCdf(Math.floor(t), n, theta)).toBeCloseTo(0.8, 9);
    }
  });

  test('Infinity when no count can flag; NaN without a usable denominator', () => {
    expect(binomialDetectableRate(5, 5)).toBe(Infinity);
    expect(Number.isNaN(binomialDetectableRate(3, 0))).toBe(true);
    expect(Number.isNaN(binomialDetectableRate(3, 10.5))).toBe(true);
  });
});

describe('funnel power reporting', () => {
  const run = (extra: Record<string, unknown> = {}) =>
    compute({ y: Y, n: N, chart: 'p', funnel: true, ...extra } as any);

  test('the trap point reports why it did not flag', () => {
    const row = run().data[0] as any;
    expect(row.sigma_signal).toBe(false);
    expect(row.min_detectable).toBeCloseTo(0.5779, 4);
    expect(row.ci_95_lower).toBeCloseTo(0.0992, 4);
    expect(row.ci_95_upper).toBeCloseTo(0.6511, 4);
  });

  test('summary and note', () => {
    const s = run().summary as any;
    expect(s.underpowered).toBe(true);
    expect(s.n_underpowered).toBe(11);
    expect(s.min_detectable_ratio_median).toBeCloseTo(2.7885, 4);
    expect(s.power_note).toContain('11 of 14');
    expect(s.power_note).toContain('proportion');
  });

  test('excluded points do not colour the verdict', () => {
    expect((run({ exclude: [1] }).summary as any).n_underpowered).toBe(10);
  });

  test('columns scale with multiply but the verdict does not', () => {
    const a = run();
    const b = run({ multiply: 100 });
    a.data.forEach((r: any, i) => {
      expect((b.data[i] as any).min_detectable / 100).toBeCloseTo(r.min_detectable, 10);
    });
    expect((b.summary as any).min_detectable_ratio_median)
      .toBeCloseTo((a.summary as any).min_detectable_ratio_median, 10);
  });

  test('absent without funnel mode', () => {
    const r = compute({ y: Y, n: N, chart: 'p' } as any);
    expect('min_detectable' in r.data[0]).toBe(false);
    expect('underpowered' in r.summary).toBe(false);
  });
});
