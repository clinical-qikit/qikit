import { describe, it, expect } from 'vitest';
import { design } from '@qikit/engine';
import { recompute } from '../src/excel/recompute';
import { DEFAULT_OPTIONS } from '../src/ui/spc/constants';

describe('recompute — spc', () => {
  it('re-runs the engine and rebuilds the sheet table from raw values', () => {
    const values: any[][] = [
      ['Date', 'Value'],
      ['2024-01-02', 10], ['2024-01-09', 11], ['2024-01-16', 9], ['2024-01-23', 12],
    ];
    const { sheetData } = recompute('spc', values, {
      xCol: 0, yCol: 1, nCol: null, notesCol: null,
      chartType: 'run', dataGrain: 'summarized', xPeriod: 'month',
      options: DEFAULT_OPTIONS, includeDataTable: false, annotations: {},
    });
    expect(sheetData[0]).toEqual(['Point', 'Value', 'CL', 'UCL', 'LCL', 'Signal']);
    expect(sheetData.length).toBeGreaterThan(1);
  });
});

describe('recompute — pareto', () => {
  it('rebuilds the Pareto table from raw values', () => {
    const values: any[][] = [['Defect Type'], ['Scratch'], ['Scratch'], ['Dent']];
    const { sheetData } = recompute('pareto', values, { xCol: 0 });
    expect(sheetData[0]).toEqual(['Category', 'Count', 'Cumulative Sum', 'Cumulative %']);
    expect(sheetData).toHaveLength(3); // header + Scratch + Dent
  });
});

describe('recompute — bchart', () => {
  it('rebuilds the CUSUM table from raw values', () => {
    const values: any[][] = [['Patient', 'Event'], [1, 0], [2, 1], [3, 0], [4, 0]];
    const { sheetData } = recompute('bchart', values, { xCol: 1, orRatio: 2.0, limit: 3.5 });
    expect(sheetData[0]).toEqual(['Point', 'Value', 'CUSUM Up', 'CUSUM Down', 'Signal Up', 'Signal Down', 'Limit']);
    expect(sheetData).toHaveLength(5); // header + 4 rows
  });
});

describe('recompute — doe', () => {
  it('rebuilds the effects table from a Response column', () => {
    const d = design({
      factors: ['A', 'B'], lows: [-1, -1], highs: [1, 1],
      design_type: 'full_factorial', replicates: 1, center_points: 0, randomize: 'none', seed: 42,
    });
    const values: any[][] = [
      ['RunOrder', 'Response'],
      ...d.matrix.map(row => [row.RunOrder, (row.A as number) * 2 + (row.B as number) * -3]),
    ];
    const { sheetData } = recompute('doe', values, { design: d });
    expect(sheetData[0]).toEqual(['Term', 'Effect', 'SS', '% Contribution']);
  });

  it('throws a descriptive error when the run count no longer matches', () => {
    const d = design({
      factors: ['A', 'B'], lows: [-1, -1], highs: [1, 1],
      design_type: 'full_factorial', replicates: 1, center_points: 0, randomize: 'none', seed: 42,
    });
    const values: any[][] = [['RunOrder', 'Response'], [1, 5]];
    expect(() => recompute('doe', values, { design: d })).toThrow(/has \d+ runs/);
  });
});
