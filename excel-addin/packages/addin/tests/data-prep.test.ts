import { describe, it, expect } from 'vitest';
import {
  parseColumns, buildSpcInput, buildNoteMap, buildSheetRows,
  colLetter, aggregateByPeriod, periodKey, toDate, formatLimit,
  SpcDataSelection,
} from '../src/ui/spc/data-prep';
import { DEFAULT_OPTIONS } from '../src/ui/spc/constants';

// Shapes mirror the dev-harness mock datasets.
const DATED_ROWS: any[][] = [
  ['Date', 'Value'],
  ['2024-01-02', 10.0], ['2024-01-15', 12.0], ['2024-01-30', 14.0],
  ['2024-02-05', 20.0], ['2024-02-20', 30.0],
];

const SUBGROUP_ROWS: any[][] = [
  ['Sample', 'Defectives', 'Total'],
  [1, 3, 50], [2, 5, 50], [3, 2, 50], [4, 8, 50],
];

function selection(partial: Partial<SpcDataSelection>): SpcDataSelection {
  return {
    rawData: [],
    hasHeaders: true,
    dateCols: [],
    xCol: null,
    yCol: 1,
    nCol: null,
    notesCol: null,
    chartType: 'run',
    dataGrain: 'summarized',
    xPeriod: 'month',
    options: DEFAULT_OPTIONS,
    ...partial,
  };
}

describe('colLetter', () => {
  it('maps indexes to Excel column letters', () => {
    expect(colLetter(0)).toBe('A');
    expect(colLetter(25)).toBe('Z');
    expect(colLetter(26)).toBe('AA');
    expect(colLetter(27)).toBe('AB');
  });
});

describe('parseColumns', () => {
  it('detects headers and classifies date/numeric columns', () => {
    const parsed = parseColumns(DATED_ROWS);
    expect(parsed.hasHeaders).toBe(true);
    expect(parsed.headers).toEqual(['Date', 'Value']);
    expect(parsed.dateCols).toEqual([0]);
    expect(parsed.numericCols).toEqual([1]);
    expect(parsed.labelCols).toEqual([]);
  });

  it('falls back to letter headers for headerless numeric data', () => {
    const parsed = parseColumns([[1, 3], [2, 5], [3, 2]]);
    expect(parsed.hasHeaders).toBe(false);
    expect(parsed.headers).toEqual(['A', 'B']);
    expect(parsed.numericCols).toEqual([0, 1]);
  });

  it('classifies non-numeric non-date columns as labels', () => {
    const parsed = parseColumns([
      ['Ward', 'Count'],
      ['ICU north wing', 3],
      ['Med-surg east', 5],
    ]);
    expect(parsed.labelCols).toEqual([0]);
    expect(parsed.numericCols).toEqual([1]);
    expect(parsed.dateCols).toEqual([]);
  });

  it('returns empty classification for fewer than 2 rows', () => {
    expect(parseColumns([['only header']])).toEqual({
      hasHeaders: false, headers: [], numericCols: [], labelCols: [], dateCols: [],
    });
  });
});

describe('aggregateByPeriod / periodKey', () => {
  it('buckets dates by month and averages continuous values', () => {
    const dates = DATED_ROWS.slice(1).map(r => toDate(r[0]));
    const ys = DATED_ROWS.slice(1).map(r => r[1] as number);
    const agg = aggregateByPeriod(dates, ys, undefined, 'month', 'mean', false);
    expect(agg.labels).toEqual(['Jan 2024', 'Feb 2024']);
    expect(agg.y).toEqual([12, 25]); // mean(10,12,14), mean(20,30)
  });

  it('sums attribute values and n per bucket', () => {
    const dates = [toDate('2024-01-02'), toDate('2024-01-20'), toDate('2024-02-01')];
    const agg = aggregateByPeriod(dates, [1, 0, 1], [10, 12, 8], 'month', 'sum', true);
    expect(agg.y).toEqual([1, 1]);
    expect(agg.n).toEqual([22, 8]);
  });

  it('produces stable period keys', () => {
    const d = toDate('2024-05-15')!;
    expect(periodKey(d, 'day')).toBe('2024-05-15');
    expect(periodKey(d, 'month')).toBe('2024-05');
    expect(periodKey(d, 'quarter')).toBe('2024-Q2');
    expect(periodKey(d, 'year')).toBe('2024');
  });
});

describe('buildSpcInput', () => {
  it('aggregates by month when X is a date column', () => {
    const prepared = buildSpcInput(selection({
      rawData: DATED_ROWS, dateCols: [0], xCol: 0, yCol: 1, chartType: 'run',
    }));
    expect(prepared).not.toBeNull();
    expect(prepared!.input.y).toEqual([12, 25]);
    expect(prepared!.xLabels).toEqual(['Jan 2024', 'Feb 2024']);
  });

  it('passes raw values and labels through for non-date X', () => {
    const prepared = buildSpcInput(selection({
      rawData: SUBGROUP_ROWS, xCol: 0, yCol: 1, nCol: 2, chartType: 'p',
    }));
    expect(prepared!.input.y).toEqual([3, 5, 2, 8]);
    expect(prepared!.input.n).toEqual([50, 50, 50, 50]);
    expect(prepared!.xLabels).toEqual(['1', '2', '3', '4']);
  });

  it('derives n=1 per row in individual grain for attribute charts', () => {
    const rows = [['Patient', 'Event'], [1, 1], [2, 0], [3, 1]];
    const prepared = buildSpcInput(selection({
      rawData: rows, yCol: 1, chartType: 'p', dataGrain: 'individual',
    }));
    expect(prepared!.input.n).toEqual([1, 1, 1]);
  });

  it('returns null when the Y column has no numeric data', () => {
    const prepared = buildSpcInput(selection({
      rawData: [['A', 'B'], ['x', 'y'], ['z', 'w']], yCol: 1,
    }));
    expect(prepared).toBeNull();
  });

  it('parses numeric option strings into engine input', () => {
    const prepared = buildSpcInput(selection({
      rawData: SUBGROUP_ROWS, yCol: 1,
      options: {
        ...DEFAULT_OPTIONS,
        freeze: '2', part: '1, 3', exclude: '2', clOverride: '4.5',
        multiply: '100', partLabels: 'Pre, Post',
      },
    }));
    expect(prepared!.input.freeze).toBe(2);
    expect(prepared!.input.part).toEqual([1, 3]);
    expect(prepared!.input.exclude).toEqual([2]);
    expect(prepared!.input.clOverride).toBe(4.5);
    expect(prepared!.input.multiply).toBe(100);
    expect(prepared!.partLabels).toEqual(['Pre', 'Post']);
  });
});

describe('buildNoteMap', () => {
  const rows = [
    ['Sample', 'Value', 'Note'],
    [1, 10, 'baseline'],
    [2, 12, ''],
    [3, 14, 'intervention'],
  ];

  it('maps notes to point indexes for non-date X', () => {
    const notes = buildNoteMap(selection({ rawData: rows, xCol: 0, yCol: 1, notesCol: 2 }));
    expect(notes).toEqual({ 0: 'baseline', 2: 'intervention' });
  });

  it('returns no notes when X is date-aggregated (row identity is discarded)', () => {
    // Pins the behavior the ColumnSelector hint documents.
    const notes = buildNoteMap(selection({
      rawData: DATED_ROWS, dateCols: [0], xCol: 0, yCol: 1, notesCol: 0,
    }));
    expect(notes).toEqual({});
  });

  it('returns no notes when no notes column is chosen', () => {
    expect(buildNoteMap(selection({ rawData: rows, yCol: 1 }))).toEqual({});
  });
});

describe('buildSheetRows', () => {
  const result = {
    data: [
      { y: 10, cl: 11, ucl: 14, lcl: 8, sigma_signal: false, runs_signal: false },
      { y: 15, cl: 11, ucl: 14, lcl: 8, sigma_signal: true, runs_signal: false },
    ],
  } as any;

  it('emits the SPC columns and flags signal points', () => {
    const { finalCols, rows } = buildSheetRows(result, {}, [], false, [], false);
    expect(finalCols).toEqual(['Point', 'Value', 'CL', 'UCL', 'LCL', 'Signal']);
    expect(rows[0]).toEqual([1, 10, 11, 14, 8, null]);
    expect(rows[1]).toEqual([2, 15, 11, 14, 8, 1]);
  });

  it('adds a Note column only when annotations exist', () => {
    const { finalCols, rows } = buildSheetRows(result, { 1: 'spike' }, [], false, [], false);
    expect(finalCols).toContain('Note');
    expect(rows[0][6]).toBeNull();
    expect(rows[1][6]).toBe('spike');
  });

  it('prepends source data columns when requested', () => {
    const raw = [['Sample', 'Value'], [1, 10], [2, 15]];
    const { finalCols, rows } = buildSheetRows(result, {}, raw, true, [], true);
    expect(finalCols).toEqual(['Sample', 'Value', 'Point', 'Value', 'CL', 'UCL', 'LCL', 'Signal']);
    expect(rows[0].slice(0, 2)).toEqual([1, 10]);
  });

  it('writes null for NaN limits (e.g. run charts without control limits)', () => {
    const runResult = {
      data: [{ y: 10, cl: 11, ucl: NaN, lcl: NaN, sigma_signal: false, runs_signal: false }],
    } as any;
    const { rows } = buildSheetRows(runResult, {}, [], false, [], false);
    expect(rows[0]).toEqual([1, 10, 11, null, null, null]);
  });
});

describe('formatLimit', () => {
  const rows = (vals: number[]) => vals.map(v => ({ cl: v }));

  it('prints a single value when the line is flat', () => {
    expect(formatLimit(rows([2.5, 2.5, 2.5]), 'cl')).toBe('2.500');
  });

  it('prints a range when the line varies', () => {
    // An S chart CL of c4(nᵢ)·σ̂ — row 0 alone would misreport it.
    expect(formatLimit(rows([1.514, 1.638, 1.682]), 'cl')).toBe('1.514–1.682');
  });

  it('collapses variation below the displayed precision', () => {
    expect(formatLimit(rows([2.5000, 2.50001]), 'cl')).toBe('2.500');
  });

  it('ignores NaN gaps but keeps the surrounding values', () => {
    expect(formatLimit(rows([1.2, NaN, 3.4]), 'cl')).toBe('1.200–3.400');
  });

  it('returns an em dash when nothing is defined', () => {
    expect(formatLimit(rows([NaN, NaN]), 'cl')).toBe('—');
    expect(formatLimit([], 'cl')).toBe('—');
  });
});
