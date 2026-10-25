import { describe, test, expect } from 'vitest';
import { compute, funnelDispersion } from '../src';
import {
  betaBinomialQuantiles, binomialQuantiles, poissonGammaQuantiles, poissonQuantileInterp,
} from '../src/stats';
import { Z_95, Z_998 } from '../src/constants';

// Mirrors TestMixtureQuantiles, TestExactFunnelLimits and TestAdjustedFunnels in
// tests/test_spc.py. The fixtures (funnel_p_*, funnel_pp_*, funnel_up_*, funnel_oep_*)
// pin the values; these pin the properties the fixtures cannot express.

const P = [0.001, 0.025, 0.975, 0.999];
const Z = [-Z_998, -Z_95, Z_95, Z_998];

describe('mixture quantiles', () => {
  // Same reference values as the Python suite: scipy.stats agrees to < 1e-9, and the
  // beta-binomial case was checked at 60 digits with mpmath.
  test.each([
    ['binomial 40, 0.15', () => binomialQuantiles(P, 40, 0.15, Z), [0.0, 1.353317438, 10.274115942, 13.407411677]],
    ['binomial 500, 0.06', () => binomialQuantiles(P, 500, 0.06, Z), [14.37069487, 19.488889585, 40.335778753, 47.099535085]],
    ['poisson-gamma 12, 4', () => poissonGammaQuantiles(P, 12, 4, Z), [0.0, 1.426666667, 28.035000962, 42.959417236]],
    ['poisson-gamma 60, 25', () => poissonGammaQuantiles(P, 60, 25, Z), [23.458676928, 34.336499809, 90.132141283, 111.962395051]],
    ['beta-binomial 800', () => {
      const s = 0.02 * 0.98 / 0.00012 ** 2 - 1;
      return betaBinomialQuantiles(P, 800, 0.02 * s, 0.98 * s, Z);
    }, [4.692840993, 8.189438538, 23.729079843, 29.00454447]],
  ])('%s', (_name, fn, expected) => {
    const [got, exact] = fn();
    expect(exact).toBe(true);
    got.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 8));
  });

  test('poisson-gamma tends to poisson as the spread vanishes', () => {
    const [got] = poissonGammaQuantiles(P, 7.3, 1e12, Z);
    got.forEach((v, i) => expect(v).toBeCloseTo(poissonQuantileInterp(P[i], 7.3), 7));
  });

  test('beta-binomial tends to binomial as the spread vanishes', () => {
    const [got] = betaBinomialQuantiles(P, 50, 0.2e12, 0.8e12, Z);
    const [ref] = binomialQuantiles(P, 50, 0.2, Z);
    got.forEach((v, i) => expect(v).toBeCloseTo(ref[i], 7));
  });

  test('a non-integer n falls back to the normal approximation and says so', () => {
    const [got, exact] = binomialQuantiles([0.999], 40.5, 0.15, [Z_998]);
    expect(exact).toBe(false);
    expect(got[0]).toBeCloseTo(40.5 * 0.15 + Z_998 * Math.sqrt(40.5 * 0.15 * 0.85), 9);
  });
});

describe('funnelDispersion', () => {
  test('matches Spiegelhalter eqs. 4, 6, 8 and 10 written out by hand', () => {
    const y = [23, 8, 34, 19, 59, 31, 72, 38, 104, 64, 120, 88];
    const n = [12, 18, 25, 30, 38, 45, 55, 64, 72, 85, 96, 110];
    const r = compute({ y, n, chart: 'oep', funnel: true });
    expect(r.summary.dispersion_phi).toBeCloseTo(6.261737, 6);
    expect(r.summary.dispersion_tau).toBeCloseTo(0.335455, 6);
  });

  test('τ̂² is zero, never negative, without heterogeneity', () => {
    const [phi, tau2] = funnelDispersion(0.1, new Array(10).fill(0.1), new Array(10).fill(100),
      new Array(10).fill(true), 'binomial');
    expect(phi).toBe(0);
    expect(tau2).toBe(0);
  });
});

describe('exact funnel limits', () => {
  const Y = [3, 7, 5, 12, 9, 20, 18, 31];
  const N = [20, 40, 55, 80, 95, 130, 160, 240];

  test('a u funnel is the Poisson funnel, exposure in place of expected events', () => {
    const u = compute({ y: Y, n: N, chart: 'u', funnel: true }).data;
    const oe = compute({ y: Y, n: N, chart: 'oe', funnel: true }).data;
    u.forEach((row, i) => {
      for (const col of ['cl', 'ucl', 'lcl', 'ucl_95', 'lcl_95']) expect(row[col]).toBe(oe[i][col]);
    });
  });

  test('time-ordered p keeps 3σ and reports no funnel keys', () => {
    const r = compute({ y: Y, n: N, chart: 'p' });
    const cl = Y.reduce((a, b) => a + b) / N.reduce((a, b) => a + b);
    expect(r.data[0].ucl).toBeCloseTo(cl + 3 * Math.sqrt(cl * (1 - cl) / N[0]), 12);
    expect(r.summary.limit_method).toBeUndefined();
    expect(r.summary.dispersion_phi).toBeUndefined();
  });

  test('dispersion_note appears only when over-dispersed', () => {
    expect(compute({ y: Y, n: N, chart: 'p', funnel: true }).summary.dispersion_note).toBeUndefined();
    const loud = compute({ y: [1, 19, 2, 40, 5, 70, 10, 120], n: N, chart: 'p', funnel: true });
    expect(loud.summary.overdispersed).toBe(true);
    expect(loud.summary.dispersion_note).toContain("chart='pp' with funnel=True");
  });
});

describe('adjusted funnels', () => {
  const COUNTS = { y: [23, 8, 34, 19, 59, 31, 72, 38, 104, 64, 120, 88],
                   n: [12, 18, 25, 30, 38, 45, 55, 64, 72, 85, 96, 110] };
  const TIGHT = { y: [12, 19, 24, 31, 37, 46, 54, 66, 71, 86, 95, 111], n: COUNTS.n };
  const TIGHT_PROPS = { y: [4, 6, 5, 8, 10, 12, 15, 21, 25, 30, 51, 60],
                        n: [40, 50, 60, 80, 100, 120, 150, 200, 250, 300, 500, 600] };

  test.each([
    ['oep', 'oe', TIGHT],
    ['pp', 'p', TIGHT_PROPS],
  ] as const)('%s equals %s exactly when τ̂ = 0', (adj, plain, d) => {
    const a = compute({ ...d, chart: adj, funnel: true });
    const b = compute({ ...d, chart: plain, funnel: true });
    expect(a.summary.dispersion_tau).toBe(0);
    a.data.forEach((row, i) => {
      for (const col of ['ucl', 'lcl', 'ucl_95', 'lcl_95']) expect(row[col]).toBe(b.data[i][col]);
    });
  });

  test('limits level off at high volume instead of closing onto θ₀', () => {
    const y = [...COUNTS.y, 10_000];
    const n = [...COUNTS.n, 10_000];
    const adj = compute({ y, n, chart: 'oep', funnel: true });
    const plain = compute({ y, n, chart: 'oe', funnel: true });
    const top = adj.data[adj.data.length - 1];
    const tau = adj.summary.dispersion_tau as number;
    expect(top.ucl - top.cl).toBeGreaterThan(0.9 * Z_998 * tau);
    const plainTop = plain.data[plain.data.length - 1];
    expect(plainTop.ucl - plainTop.cl).toBeLessThan(0.1 * (top.ucl - top.cl));
  });

  test('up and oep are the same model', () => {
    const up = compute({ ...COUNTS, chart: 'up', funnel: true }).data;
    const oep = compute({ ...COUNTS, chart: 'oep', funnel: true }).data;
    up.forEach((row, i) => expect(row.ucl).toBe(oep[i].ucl));
  });

  test('time-ordered pp/up stay Laney', () => {
    expect(compute({ ...TIGHT_PROPS, chart: 'pp' }).summary.dispersion_method).toBe('laney');
  });

  test('multiply does not change the estimate', () => {
    const base = compute({ ...COUNTS, chart: 'oep', funnel: true });
    const x100 = compute({ ...COUNTS, chart: 'oep', funnel: true, multiply: 100 });
    expect(x100.summary.dispersion_tau).toBe(base.summary.dispersion_tau);
    expect(x100.data[0].ucl).toBeCloseTo(base.data[0].ucl * 100, 9);
  });
});
