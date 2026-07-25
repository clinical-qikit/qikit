import { describe, it, expect } from 'vitest';
import { paretochart } from '@qikit/engine';
import { buildParetoValues, buildParetoSheetRows } from '../src/ui/pareto/data-prep';

const ROWS: any[][] = [
  ['Defect Type'],
  ['Scratch'], ['Scratch'], ['Dent'], ['Scratch'], ['Crack'],
];

describe('buildParetoValues', () => {
  it('strips the header row and blanks', () => {
    const values = buildParetoValues(ROWS, true, 0);
    expect(values).toEqual(['Scratch', 'Scratch', 'Dent', 'Scratch', 'Crack']);
  });

  it('reads every row when there is no header', () => {
    const values = buildParetoValues(ROWS.slice(1), false, 0);
    expect(values).toHaveLength(5);
  });

  it('throws when the column has no values', () => {
    expect(() => buildParetoValues([['Defect Type']], true, 0)).toThrow(/No values/);
  });
});

describe('buildParetoSheetRows', () => {
  it('matches the layout createParetoChart expects', () => {
    const result = paretochart({ x: buildParetoValues(ROWS, true, 0) });
    const sheetData = buildParetoSheetRows(result);
    expect(sheetData[0]).toEqual(['Category', 'Count', 'Cumulative Sum', 'Cumulative %']);
    expect(sheetData).toHaveLength(result.data.length + 1);
    expect(sheetData[1][0]).toBe(result.data[0].category);
  });
});
