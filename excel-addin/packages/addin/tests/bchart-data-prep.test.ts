import { describe, it, expect } from 'vitest';
import { bchart } from '@qikit/engine';
import { buildBChartValues, buildBChartSheetRows } from '../src/ui/bchart/data-prep';

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
});

describe('buildBChartSheetRows', () => {
  it('matches the layout createBChartChart expects', () => {
    const result = bchart({ x: buildBChartValues(ROWS, true, 1) });
    const sheetData = buildBChartSheetRows(result);
    expect(sheetData[0]).toEqual(['Point', 'Value', 'CUSUM Up', 'CUSUM Down', 'Signal Up', 'Signal Down', 'Limit']);
    expect(sheetData).toHaveLength(result.data.length + 1);
  });
});
