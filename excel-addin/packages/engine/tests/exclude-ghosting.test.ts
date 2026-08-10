import { describe, test, expect } from 'vitest';
import { compute } from '../src';

// exclude= removes a point from the baseline *and* ghosts it out of signal
// detection entirely — it neither flags nor breaks a run. freeze/part only
// narrow the baseline; their boundary points are still checked against it.
// Mirrors src/qikit/spc/compute.py.
describe('excluded points are ghosted from signal detection', () => {
  const outlier = { y: [10, 11, 9, 12, 45, 10, 11, 9, 12, 10], n: 100, chart: 'p' as const };

  test('an excluded outlier is not flagged against the limits it is excluded from', () => {
    const { data, summary } = compute({ ...outlier, exclude: [5] });
    expect(data[4].y).toBeCloseTo(0.45, 9);   // still plotted at its real value
    expect(data[4].ucl).toBeCloseTo(0.19619531486114525, 9);
    expect(data[4].sigma_signal).toBe(false); // ...but not flagged
    expect(summary.signals).toBe(false);
  });

  test('without exclude the same point does signal', () => {
    const { data, summary } = compute(outlier);
    expect(data[4].sigma_signal).toBe(true);
    expect(summary.signals).toBe(true);
  });

  test('a ghosted point does not break a run', () => {
    // 11 points below CL with an excluded spike in the middle: the run reads as
    // unbroken, and the ghost is not counted as one of its points (Python: 11).
    const y = [1, 1, 1, 1, 1, 99, 1, 1, 1, 1, 1, 1, 9, 9, 9, 9, 9, 9];
    const withGhost = compute({ y, chart: 'i', exclude: [6] });
    expect(withGhost.data[5].runs_signal_localized).toBe(false);
    expect(withGhost.summary.longest_run).toBe(11);
  });

  test('a bare exclude index means the same as a one-element list', () => {
    const scalar = compute({ ...outlier, exclude: 5 });
    const listed = compute({ ...outlier, exclude: [5] });
    expect(scalar.data[4].sigma_signal).toBe(false);
    expect(scalar.data[0].cl).toBeCloseTo(listed.data[0].cl, 12);
  });

  test('a bare part index means the same as a one-element list', () => {
    const y = [1, 1, 1, 1, 1, 9, 9, 9, 9, 9];
    const scalar = compute({ y, chart: 'i', part: 6 });
    const listed = compute({ y, chart: 'i', part: [6] });
    expect(scalar.data.map(d => d.cl)).toEqual(listed.data.map(d => d.cl));
    expect(scalar.data[0].cl).not.toBeCloseTo(scalar.data[9].cl, 6);
  });

  test('freeze does not ghost — boundary points stay checkable', () => {
    // freeze narrows the baseline but every point is still tested against it.
    const { data } = compute({ y: [10, 10, 10, 10, 40], chart: 'i', freeze: 4 });
    expect(data[4].sigma_signal).toBe(true);
  });
});
