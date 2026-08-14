import { describe, test, expect } from 'vitest';
import { crossingsThreshold, longestRunThreshold } from '../src';

// Anhoej & Olesen (2014) thresholds — mirrors the Python engine
// (src/qikit/spc/signals.py, TestAnhoejThresholds in tests/test_spc.py).
// The expected values below are shared by both engines; the large-n cases are
// verified against exact rational arithmetic on the Python side.
describe('anhoej thresholds', () => {
  test('longest-run threshold is floor(log2(n)) + 3, impossible below n=10', () => {
    expect(longestRunThreshold(10)).toBe(6);
    expect(longestRunThreshold(20)).toBe(7);
    expect(longestRunThreshold(100)).toBe(9);
    expect(longestRunThreshold(5)).toBeGreaterThan(5);
  });

  test('crossings threshold at small n', () => {
    expect(crossingsThreshold(10)).toBe(1);
    expect(crossingsThreshold(20)).toBe(5);
    expect(crossingsThreshold(100)).toBe(40);
    expect(crossingsThreshold(1000)).toBe(473);
  });

  test('crossings threshold is -1 below n=10 (no signalling)', () => {
    for (const n of [1, 5, 9]) expect(crossingsThreshold(n)).toBe(-1);
  });

  test('crossings threshold stays exact past n=1032', () => {
    // The binomial coefficient overflowed to Infinity here, which silently
    // returned wrong thresholds (and raised OverflowError in Python).
    expect(crossingsThreshold(1033)).toBe(489);
    expect(crossingsThreshold(1500)).toBe(717);
    expect(crossingsThreshold(3000)).toBe(1453);
    expect(crossingsThreshold(5000)).toBe(2440);
  });

  test('crossings threshold stays below n/2 at large n', () => {
    for (const n of [1033, 2000, 10000]) {
      expect(crossingsThreshold(n)).toBeLessThan(n / 2);
    }
  });
});
