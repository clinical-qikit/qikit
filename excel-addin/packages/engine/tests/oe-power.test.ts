import { describe, test, expect } from 'vitest';
import { compute } from '../src';
import { oeDetectableRatio, oePointCi } from '../src/spc-core';
import { poissonCdf, poissonMeanForCdf } from '../src/stats';

// Twin of TestOEDetectability / TestOEPointCI in tests/test_spc.py. The shared
// fixtures already prove the column values match Python; these cover the anchors and
// the error paths a fixture cannot express.

const PHYS_Y = [12, 8, 8, 3, 20, 14, 31, 26, 55, 48, 72, 110];
const PHYS_N = [5.0, 3.2, 6.5, 4.1, 12.0, 15.5, 28.0, 30.0, 52.0, 60.0, 70.0, 62.0];

describe('poissonCdf', () => {
  test('known values', () => {
    expect(poissonCdf(3, 5)).toBeCloseTo(0.2650259, 7);
    expect(poissonCdf(2, 5)).toBeCloseTo(0.1246520, 7);
    expect(poissonCdf(0, 1)).toBeCloseTo(Math.exp(-1), 10);
  });

  test('edges', () => {
    expect(poissonCdf(-1, 5)).toBe(0.0);
    expect(poissonCdf(3, 0)).toBe(1.0);   // all mass at zero
    expect(Number.isNaN(poissonCdf(3, NaN))).toBe(true);
  });
});

describe('poissonMeanForCdf', () => {
  test('inverts the CDF', () => {
    // 8 rather than more: the solve is quantized to 1e-9 for cross-platform
    // reproducibility, which shows up here as ~2e-10 of slack.
    for (const k of [0, 1, 3, 10, 50, 200]) {
      for (const p of [0.025, 0.2, 0.5, 0.975]) {
        expect(poissonCdf(k, poissonMeanForCdf(k, p))).toBeCloseTo(p, 8);
      }
    }
  });

  test('throws above the solve ceiling', () => {
    expect(() => poissonMeanForCdf(1e4 + 1, 0.5)).toThrow(/solve ceiling/);
  });
});

describe('oePointCi', () => {
  test('Garwood anchors', () => {
    // Published exact Poisson interval for 10 observed events.
    const [lo, hi] = oePointCi(10, 1.0);
    expect(lo).toBeCloseTo(4.795, 3);
    expect(hi).toBeCloseTo(18.390, 3);
  });

  test('zero observed gives a lower bound of exactly zero', () => {
    const [lo, hi] = oePointCi(0, 5.0);
    expect(lo).toBe(0.0);
    expect(hi).toBeCloseTo(-Math.log(0.025) / 5.0, 10);
  });

  test('NaN when there is no usable expected count', () => {
    expect(oePointCi(3, 0)).toEqual([NaN, NaN]);
    expect(oePointCi(-1, 5)).toEqual([NaN, NaN]);
  });
});

describe('oeDetectableRatio', () => {
  test('achieves exactly 80% power at the returned ratio', () => {
    for (const e of [2, 5, 10, 20, 50]) {
      const t = 1.5 * e;                      // any plausible count-scale threshold
      const rho = oeDetectableRatio(t, e);
      expect(1 - poissonCdf(Math.floor(t), rho * e)).toBeCloseTo(0.8, 9);
    }
  });

  test('NaN without a usable expected count', () => {
    expect(Number.isNaN(oeDetectableRatio(5, 0))).toBe(true);
    expect(Number.isNaN(oeDetectableRatio(Infinity, 5))).toBe(true);
  });
});

describe('O/E power reporting', () => {
  test('columns and summary appear on a physician-scale funnel', () => {
    const r = compute({ y: PHYS_Y, n: PHYS_N, chart: 'oe', funnel: true });
    const row: any = r.data[0];
    // Row 0 is the smallest-E physician: 2.5x expected mortality, yet no signal.
    expect(row.sigma_signal).toBe(false);
    expect(row.min_detectable_oe).toBeCloseTo(4.265852, 5);
    expect(row.ci_95_lower).toBeCloseTo(1.079323, 5);
    expect(row.ci_95_upper).toBeCloseTo(4.925997, 5);
    expect(r.summary.underpowered).toBe(true);
    expect(r.summary.n_underpowered).toBe(8);
    expect(r.summary.power_note).toMatch(/not evidence of acceptable performance/);
  });

  test('a well-powered funnel reports no power_note', () => {
    const n = PHYS_N.map(() => 400);
    const r = compute({ y: PHYS_Y.map(() => 400), n, chart: 'oe', funnel: true });
    expect(r.summary.underpowered).toBe(false);
    expect(r.summary.power_note).toBeUndefined();
  });

  test('columns are absent on charts that are not O/E', () => {
    const r = compute({ y: [3, 2, 6, 2], n: [90, 113, 105, 102], chart: 'u' });
    expect('min_detectable_oe' in (r.data[0] as any)).toBe(false);
    expect(r.summary.underpowered).toBeUndefined();
  });
});

describe('multiply', () => {
  test('scales the new columns but not the power thresholds', () => {
    const base = compute({ y: PHYS_Y, n: PHYS_N, chart: 'oe' });
    const x100 = compute({ y: PHYS_Y, n: PHYS_N, chart: 'oe', multiply: 100 });
    expect((x100.data[0] as any).min_detectable_oe)
      .toBeCloseTo((base.data[0] as any).min_detectable_oe * 100, 6);
    expect((x100.data[0] as any).ci_95_upper)
      .toBeCloseTo((base.data[0] as any).ci_95_upper * 100, 6);
    // Thresholds are statements about the unscaled ratio.
    expect(x100.summary.min_detectable_oe_median)
      .toBeCloseTo(base.summary.min_detectable_oe_median as number, 9);
    expect(x100.summary.n_underpowered).toBe(base.summary.n_underpowered);
  });

  test('dispersion_phi is multiply-invariant', () => {
    // Regression: the summary previously fed the multiply-scaled centre line into
    // oeDispersionPhi against raw ratios, silently corrupting φ̂ whenever multiply≠1.
    const y = [23, 8, 34, 19, 59, 31, 72, 38];
    const n = [12, 18, 25, 30, 38, 45, 55, 64];
    const base = compute({ y, n, chart: 'oep', funnel: true }).summary.dispersion_phi;
    const x2 = compute({ y, n, chart: 'oep', funnel: true, multiply: 2 }).summary.dispersion_phi;
    expect(x2).toBeCloseTo(base as number, 10);
  });
});
