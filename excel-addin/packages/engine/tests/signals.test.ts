import { describe, test, expect } from 'vitest';
import { longestRunMax, nCrossingsMin } from '../src';

// Anhoej & Olesen (2014) thresholds — mirrors the Python engine
// (src/qikit/spc/signals.py, TestAnhoejThresholds in tests/test_spc.py).
// The expected values below are shared by both engines; the large-n cases are
// verified against exact rational arithmetic on the Python side.
describe('anhoej thresholds', () => {
  // As qicharts2 computes them: a run longer than round(log2 n) + 3 signals, and fewer
  // crossings than qbinom(0.05, n - 1, 0.5). Mirrors TestAnhoejThresholds in Python.
  test('longest run expected by chance is round(log2 n) + 3', () => {
    expect(longestRunMax(10)).toBe(6);
    expect(longestRunMax(20)).toBe(7);
    expect(longestRunMax(100)).toBe(10);
    expect(longestRunMax(5)).toBe(5);
  });

  test('fewest crossings expected by chance is qbinom(0.05, n - 1, 0.5)', () => {
    expect(nCrossingsMin(10)).toBe(2);
    expect(nCrossingsMin(20)).toBe(6);
    expect(nCrossingsMin(100)).toBe(41);
    expect(nCrossingsMin(1000)).toBe(474);
  });

  test('stays exact past n = 1032', () => {
    expect(nCrossingsMin(1033)).toBe(490);
    expect(nCrossingsMin(1500)).toBe(718);
    expect(nCrossingsMin(3000)).toBe(1454);
    expect(nCrossingsMin(5000)).toBe(2441);
  });
});
