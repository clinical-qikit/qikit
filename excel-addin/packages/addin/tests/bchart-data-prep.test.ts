import { describe, it, expect } from 'vitest';
import { bchart } from '@qikit/engine';
import { buildBChartValues, buildBChartSheetRows, firstBinaryColumn } from '../src/ui/bchart/data-prep';

const ROWS: any[][] = [
  ['Patient', 'Adverse Event'],
  [1, 0], [2, 1], [3, 0], [4, 0], [5, 1],
];

describe('buildBChartValues', () => {
  it('strips the header row and non-numeric cells', () => {
    const values = buildBChartValues(ROWS, true, 1);
    expect(values).toEqual([0, 1, 0, 0, 1]);
  });

  it('throws when the column has no numeric values', () => {
    expect(() => buildBChartValues([['Patient', 'Adverse Event'], [1, 'n/a']], true, 1)).toThrow(/No numeric/);
  });

  it('skips blank cells instead of counting them as 0', () => {
    expect(buildBChartValues([['Event'], [1], [''], [null], [0]], true, 0)).toEqual([1, 0]);
  });

  it('names the column when it is not 0/1 outcomes', () => {
    expect(() => buildBChartValues(ROWS, true, 0))
      .toThrow('The "Patient" column has values other than 0 and 1 (such as 2).');
  });
});

describe('firstBinaryColumn', () => {
  it('skips an ID column to the 0/1 outcomes', () => {
    expect(firstBinaryColumn(ROWS, true)).toBe(1);
  });

  it('falls back to the first column when none is 0/1', () => {
    expect(firstBinaryColumn([['a', 'b'], [3, 4]], true)).toBe(0);
  });
});

describe('buildBChartSheetRows', () => {
  it('matches the layout createBChartChart expects', () => {
    const result = bchart({ x: buildBChartValues(ROWS, true, 1) });
    const sheetData = buildBChartSheetRows(result);
    expect(sheetData[0]).toEqual(['Point', 'Value', 'CUSUM Up', 'CUSUM Down', 'Signal Up', 'Signal Down', 'Limit']);
    expect(sheetData).toHaveLength(result.data.length + 1);
  });
});
