import { describe, test, expect } from 'vitest';
import { compute } from '../src';

// Funnel mode reorders points by denominator ascending. exclude is 1-based into
// the *input* order and must follow that sort; freeze/part assume time order and
// are rejected. Mirrors src/qikit/spc/api.py — the value assertions here are the
// error paths that fixtures/spc/funnel_p_exclude.json cannot express.
describe('funnel mode', () => {
  // n ascending is [5, 50, 500, 5000] — input order 1, 3, 2, 4.
  const p = { y: [4, 480, 55, 4700], n: [5, 500, 50, 5000], chart: 'p' as const, funnel: true };

  test('exclude follows the denominator sort', () => {
    // The n=500 point is input index 2 (1-based) and sorts to position 3.
    const cl = compute({ ...p, exclude: [2] }).data[0].cl;
    expect(cl).toBeCloseTo((4 + 55 + 4700) / (5 + 50 + 5000), 9);
  });

  test('excluding a different input index drops a different point', () => {
    // The engine emits no per-row `excluded` flag, so the center line is the
    // observable: index 2 is the n=500 point, index 3 is the n=50 point.
    expect(compute({ ...p, exclude: [2] }).data[0].cl)
      .toBeCloseTo((4 + 55 + 4700) / (5 + 50 + 5000), 9);
    expect(compute({ ...p, exclude: [3] }).data[0].cl)
      .toBeCloseTo((4 + 480 + 4700) / (5 + 500 + 5000), 9);
  });

  test('out-of-range exclude indices are ignored', () => {
    const { data } = compute({ ...p, exclude: [99] });
    expect(data.some(d => d.excluded)).toBe(false);
  });

  test('funnel rejects freeze', () => {
    expect(() => compute({ ...p, freeze: 2 })).toThrow(/funnel/);
  });

  test('funnel rejects part', () => {
    expect(() => compute({ ...p, part: [3] })).toThrow(/funnel/);
  });
});
