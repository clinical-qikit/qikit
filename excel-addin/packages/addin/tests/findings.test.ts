import { describe, it, expect } from 'vitest';
import { compute } from '@qikit/engine';
import { describeFindings, baselineCount } from '../src/ui/spc/findings';
import { buildSpcInput, parseColumns } from '../src/ui/spc/data-prep';
import { DEFAULT_OPTIONS } from '../src/ui/spc/constants';
import { sampleRows, SAMPLE_FORMATS } from '../src/ui/spc/sample-data';
import { chooseChart } from '../src/ui/spc/ChartChooser';

function sample() {
  const values = sampleRows();
  const formats = values.map((_, r) => (r === 0 ? ['General', 'General'] : SAMPLE_FORMATS.map(f => f ?? 'General')));
  const parsed = parseColumns(values, formats);
  const prepared = buildSpcInput({
    rawData: values, hasHeaders: parsed.hasHeaders, dateCols: parsed.dateCols,
    xCol: parsed.dateCols[0], yCol: 1, nCol: null, notesCol: null, chartType: 'run',
    dataGrain: 'summarized', xPeriod: 'month', options: DEFAULT_OPTIONS,
  })!;
  return { parsed, prepared };
}

describe('sample data', () => {
  it('reads as 24 monthly points with a date axis', () => {
    const { parsed, prepared } = sample();
    expect(parsed.dateCols).toEqual([0]);
    expect(prepared.input.y).toHaveLength(24);
    expect(prepared.xLabels![0]).toBe('Jan 2025');
    expect(prepared.skipped).toEqual([]);
  });

  it('describes its two shifts in words', () => {
    const { prepared } = sample();
    const result = compute(prepared.input);
    const f = describeFindings(result, { xLabels: prepared.xLabels });
    expect(f.verdict).toBe('Signal.');
    expect(f.details).toContain('A shift: 12 points in a row above the center line, Jan 2025 to Dec 2025.');
    expect(f.details).toContain('A shift: 12 points in a row below the center line, Jan 2026 to Dec 2026.');
    expect(f.details).toContain(
      'The line crosses the center line only once (fewer than 8 is a signal): the points cluster or drift rather than vary at random.');
    expect(f.notes).toEqual([]);
  });
});

describe('describeFindings', () => {
  const stable = [10, 12, 11, 13, 10, 12, 11, 13, 12, 10, 11, 12, 13, 11, 12, 10, 12, 11, 13, 11, 12, 10];

  it('says stable when nothing is flagged and there are enough points', () => {
    const f = describeFindings(compute({ y: stable, chart: 'i' }));
    expect(f.signal).toBe(false);
    expect(f.verdict).toBe('No signal: the process looks stable.');
    expect(f.details).toEqual([]);
  });

  it('warns under 12 baseline points, in the Python wording', () => {
    const f = describeFindings(compute({ y: stable.slice(0, 8), chart: 'run' }));
    expect(f.verdict).toBe('No signal so far, with too few points to call the process stable.');
    expect(f.notes[0]).toMatch(/^Only 8 point\(s\) set the center line: too few to judge/);
  });

  it('calls control limits on fewer than 20 points provisional', () => {
    const f = describeFindings(compute({ y: stable.slice(0, 15), chart: 'i' }));
    expect(f.notes[0]).toBe('The control limits rest on 15 points: treat them as provisional until there are 20 or more.');
  });

  it('names points outside the limits by their labels', () => {
    const y = [...stable.slice(0, 15), 40, ...stable.slice(15)];
    const labels = y.map((_, i) => `W${i + 1}`);
    const f = describeFindings(compute({ y, chart: 'i' }), { xLabels: labels });
    expect(f.details[0]).toBe('1 point is outside the control limits: W16.');
  });

  it('counts the baseline from the freeze point or the last phase', () => {
    const r = compute({ y: stable, chart: 'i' });
    expect(baselineCount(r, { freeze: 9 })).toBe(9);
    expect(baselineCount(r, { part: [12] })).toBe(stable.length - 11);
    const f = describeFindings(compute({ y: stable, chart: 'i', freeze: 9 }), { freeze: 9 });
    expect(f.notes).toContain('The center line and limits come from the first 9 points (Freeze baseline); later points are judged against them.');
  });
});

describe('chooseChart', () => {
  it('maps the answers to a chart', () => {
    expect(chooseChart(null, null, null)).toBeNull();
    expect(chooseChart('unsure', null, null)!.chart).toBe('run');
    expect(chooseChart('measure', null, null)).toBeNull();
    expect(chooseChart('measure', null, 'one')!.chart).toBe('i');
    expect(chooseChart('measure', null, 'several')!.chart).toBe('xbar');
    expect(chooseChart('measure', null, 'unsure')!.chart).toBe('run');
    expect(chooseChart('count', 'cases', null)!.chart).toBe('p');
    expect(chooseChart('count', 'exposure', null)!.chart).toBe('u');
    expect(chooseChart('count', 'none', null)!.chart).toBe('c');
    expect(chooseChart('count', 'unsure', null)!.chart).toBe('run');
  });
});
