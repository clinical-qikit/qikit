import { describe, test, expect } from 'vitest';
import { compute } from '../src';

// connect / y_percent resolution rules — mirrors Python qic() semantics
// (src/qikit/spc/api.py): y_percent defaults to true for p/pp; connect
// null means "renderer infers from x-axis"; funnel forces connect=false.
describe('display hints', () => {
  const p = { y: [5, 8, 3, 6, 4], n: [50, 80, 40, 60, 45] };

  test('y_percent defaults true for p and pp, false otherwise', () => {
    expect(compute({ ...p, chart: 'p' }).y_percent).toBe(true);
    expect(compute({ ...p, chart: 'pp' }).y_percent).toBe(true);
    expect(compute({ ...p, chart: 'u' }).y_percent).toBe(false);
    expect(compute({ y: [1, 2, 3, 2, 1], chart: 'i' }).y_percent).toBe(false);
  });

  test('explicit yPercent overrides the chart default', () => {
    expect(compute({ ...p, chart: 'p', yPercent: false }).y_percent).toBe(false);
    expect(compute({ ...p, chart: 'u', yPercent: true }).y_percent).toBe(true);
  });

  test('connect is null (infer) by default and passes through explicitly', () => {
    expect(compute({ ...p, chart: 'p' }).connect).toBeNull();
    expect(compute({ ...p, chart: 'p', connect: true }).connect).toBe(true);
    expect(compute({ ...p, chart: 'p', connect: false }).connect).toBe(false);
  });

  test('funnel mode forces connect=false even when requested true', () => {
    expect(compute({ ...p, chart: 'p', funnel: true, connect: true }).connect).toBe(false);
  });

  test('hints are included in to_dict()', () => {
    const dict = compute({ ...p, chart: 'p', funnel: true }).to_dict();
    expect(dict.connect).toBe(false);
    expect(dict.y_percent).toBe(true);
  });
});
