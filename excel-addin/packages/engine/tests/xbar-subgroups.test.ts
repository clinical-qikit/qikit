import { describe, test, expect } from 'vitest';
import { compute } from '../src';
import { A3, B3, B4, a3, b3, b4, c4 } from '../src/constants';

// Subgroup constants and per-subgroup xbar/s limits — mirrors
// src/qikit/spc/constants.py and src/qikit/spc/limits.py.
//
// The shared fixtures in fixtures/spc/ cannot express varying subgroup sizes: the
// conformance harness flattens the y column and subgroups by fixed-size chunking on
// a single subgroupN. These tests cover what the fixture schema cannot reach.

describe('subgroup constants', () => {
  test('tabulated values are exact for n = 2..25', () => {
    for (let n = 2; n <= 25; n++) {
      expect(a3(n)).toBe(A3[n]);
      expect(b3(n)).toBe(B3[n]);
      expect(b4(n)).toBe(B4[n]);
    }
  });

  test('analytic form takes over above the table', () => {
    const n = 100;
    const c = 1 - 1 / (4 * n) - 7 / (32 * n * n);
    const spread = (3 * Math.sqrt(1 - c * c)) / c;
    expect(a3(n)).toBeCloseTo(3 / (c * Math.sqrt(n)), 12);
    expect(b4(n)).toBeCloseTo(1 + spread, 12);
    expect(b3(n)).toBeCloseTo(Math.max(0, 1 - spread), 12);
  });

  test('matches the Python constants at the seam and above', () => {
    // Values produced by src/qikit/spc/constants.py — the cross-language contract.
    expect(a3(25)).toBeCloseTo(0.606, 10);
    expect(a3(26)).toBeCloseTo(0.594255, 6);
    expect(a3(30)).toBeCloseTo(0.552461, 6);
    expect(b4(30)).toBeCloseTo(1.395454, 6);
    expect(b3(30)).toBeCloseTo(0.604546, 6);
    expect(a3(1000)).toBeCloseTo(0.094892, 6);
  });

  test('seam at 25/26 does not jump', () => {
    expect(Math.abs(a3(25) - a3(26))).toBeLessThan(0.02);
    expect(Math.abs(b4(25) - b4(26))).toBeLessThan(0.01);
  });

  test('undefined below n = 2', () => {
    for (const n of [0, 1]) {
      expect(a3(n)).toBeNaN();
      expect(b3(n)).toBeNaN();
      expect(b4(n)).toBeNaN();
      expect(c4(n)).toBeNaN();
    }
  });
});

describe('xbar/s limits vary per subgroup', () => {
  // Pre-aggregated input: y holds subgroup means, n holds subgroup sizes, no
  // subgroupN so the chunking block is skipped.
  const sBar = 2;

  test('xbar uses each subgroup own size', () => {
    const r = compute({ chart: 'xbar', y: [10, 10, 10], n: [5, 10, 5], sBar });
    const ucl = r.data.map((row: any) => row.ucl);
    expect(ucl[0]).toBeCloseTo(10 + a3(5) * sBar, 10);
    expect(ucl[1]).toBeCloseTo(10 + a3(10) * sBar, 10);
    expect(ucl[0]).not.toBeCloseTo(ucl[1], 5);
    expect(ucl[0]).toBeCloseTo(ucl[2], 10);
  });

  test('s uses each subgroup own size', () => {
    const r = compute({ chart: 's', y: [2, 2, 2], n: [5, 10, 5] });
    const cl = r.data[0].cl;
    expect(r.data[0].ucl).toBeCloseTo(B4[5] * cl, 10);
    expect(r.data[1].ucl).toBeCloseTo(B4[10] * cl, 10);
    expect(r.data[0].ucl).toBeCloseTo(r.data[2].ucl, 10);
  });

  test('subgroup sizes above 25 give finite limits, not NaN', () => {
    const r = compute({ chart: 'xbar', y: [10, 10], n: [2000, 2000], sBar });
    for (const row of r.data) {
      expect(Number.isFinite(row.ucl)).toBe(true);
      expect(Number.isFinite(row.lcl)).toBe(true);
    }
    expect(r.data[0].ucl).toBeCloseTo(10 + a3(2000) * sBar, 10);
  });

  test('size-1 subgroup is a gap, not a crash', () => {
    const r = compute({ chart: 'xbar', y: [10, 10, 10], n: [5, 1, 5], sBar });
    expect(r.data[1].ucl).toBeNaN();
    expect(Number.isFinite(r.data[0].ucl)).toBe(true);
  });

  test('pooled sigmaHat switches to the 3s/sqrt(n) form', () => {
    const sigmaHat = 3;
    const r = compute({ chart: 'xbar', y: [10, 10], n: [4, 100], sigmaHat });
    expect(r.data[0].ucl).toBeCloseTo(10 + (3 * sigmaHat) / Math.sqrt(4), 10);
    expect(r.data[1].ucl).toBeCloseTo(10 + (3 * sigmaHat) / Math.sqrt(100), 10);
  });
});

describe('s chart center line varies with subgroup size', () => {
  // Mirrors TestSChartVaryingCenterLine in tests/test_spc.py. On the pooled-σ̂ path
  // the S chart center line is c4(nᵢ)·σ̂, not a flat S̄ — E[sᵢ] rises with n, and the
  // CL is what the runs detector tests each point against.
  const sigmaHat = 4;

  test('cl tracks c4(n) and equal sizes share a value', () => {
    const r = compute({ chart: 's', y: [4, 4, 4, 4], n: [4, 4, 30, 30], sigmaHat });
    const cl = r.data.map((row: any) => row.cl);

    expect(cl[0]).toBeCloseTo(sigmaHat * c4(4), 10);
    expect(cl[2]).toBeCloseTo(sigmaHat * c4(30), 10);
    expect(cl[0]).toBeCloseTo(cl[1], 10);
    expect(cl[0]).toBeLessThan(cl[2]);
  });

  test('limits are symmetric about the per-point cl', () => {
    const r = compute({ chart: 's', y: [4, 4, 4], n: [8, 15, 30], sigmaHat });
    for (const row of r.data as any[]) {
      expect(row.lcl).toBeGreaterThan(0);          // not floored, so symmetry is testable
      expect(row.ucl - row.cl).toBeCloseTo(row.cl - row.lcl, 10);
    }
  });

  test('warning bands follow the varying cl', () => {
    const r = compute({ chart: 's', y: [4, 4, 4], n: [8, 15, 30], sigmaHat });
    for (const row of r.data as any[]) {
      expect(row.ucl_95).toBeCloseTo(row.cl + (row.ucl - row.cl) * (2 / 3), 10);
    }
  });

  test('clOverride outranks the per-point cl', () => {
    const r = compute({ chart: 's', y: [4, 4, 4, 4], n: [4, 4, 30, 30], sigmaHat, clOverride: 1.5 });
    for (const row of r.data as any[]) expect(row.cl).toBe(1.5);
  });

  test('size-1 subgroup leaves a gap in the cl too', () => {
    const r = compute({ chart: 's', y: [4, 4, 4], n: [6, 1, 20], sigmaHat });
    expect(r.data[1].cl).toBeNaN();
    expect(Number.isFinite(r.data[0].cl)).toBe(true);
    expect(Number.isFinite(r.data[2].cl)).toBe(true);
  });

  test('equal n keeps the classical flat S-bar', () => {
    // No sigmaHat -> B3/B4 path -> scalar center, unchanged from before.
    const r = compute({ chart: 's', y: [2, 3, 4], n: [5, 5, 5] });
    const cl = r.data.map((row: any) => row.cl);
    expect(cl[0]).toBeCloseTo(3, 10);             // mean of [2, 3, 4]
    expect(cl[0]).toBe(cl[1]);
    expect(cl[1]).toBe(cl[2]);
  });
});

describe('fixed-size chunking', () => {
  // 22 values, subgroupN 6 -> chunks of 6, 6, 6, 4. The trailing chunk is genuinely
  // smaller and must not borrow the full-subgroupN constant.
  const y = Array.from({ length: 22 }, (_, i) => (i % 2 === 0 ? 9.5 : 10.5));

  test('trailing partial chunk uses its own size', () => {
    const r = compute({ chart: 'xbar', y, subgroupN: 6 });
    expect(r.data).toHaveLength(4);
    const half = r.data.map((row: any) => row.ucl - row.cl);
    expect(half[0]).toBeCloseTo(half[1], 10);
    expect(half[0]).toBeCloseTo(half[2], 10);
    // n = 4 vs n = 6 -> a visibly wider band on the short chunk.
    expect(half[3]).toBeGreaterThan(half[0]);
  });

  test('derives sBar for equal chunks when the caller supplies none', () => {
    const r = compute({ chart: 'xbar', y: y.slice(0, 18), subgroupN: 6 });
    const sd = Math.sqrt((6 * 0.25) / 5);
    expect(r.data[0].ucl).toBeCloseTo(10 + A3[6] * sd, 10);
  });

  test('handles subgroups larger than the constant table', () => {
    const big = Array.from({ length: 400 }, (_, i) => (i % 2 === 0 ? 9.5 : 10.5));
    const r = compute({ chart: 'xbar', y: big, subgroupN: 100 });
    expect(r.data).toHaveLength(4);
    const sd = Math.sqrt((100 * 0.25) / 99);
    expect(r.data[0].ucl).toBeCloseTo(10 + a3(100) * sd, 10);
  });
});
