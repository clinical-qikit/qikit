import { describe, it, expect } from 'vitest';
import { design, analyze } from '@qikit/engine';
import { extractResponse, buildEffectsSheetRows } from '../src/ui/doe/data-prep';

function makeDesign() {
  return design({
    factors: ['A', 'B'],
    lows: [-1, -1],
    highs: [1, 1],
    design_type: 'full_factorial',
    replicates: 1,
    center_points: 0,
    randomize: 'none',
    seed: 42,
  });
}

describe('extractResponse', () => {
  it('reads the Response column in run order', () => {
    const d = makeDesign();
    const values = [
      ['RunOrder', 'A', 'B', 'Response'],
      ...d.matrix.map(row => [row.RunOrder, row.A, row.B, (row.RunOrder as number) * 10]),
    ];
    const response = extractResponse(values, d);
    expect(response).toHaveLength(d.n_runs);
    expect(response[0]).toBe((d.matrix[0].RunOrder as number) * 10);
  });

  it('throws when there is no Response header', () => {
    const d = makeDesign();
    expect(() => extractResponse([['RunOrder', 'A', 'B']], d)).toThrow(/No 'Response' column/);
  });

  it('throws when the response count does not match the design', () => {
    const d = makeDesign();
    const values = [['RunOrder', 'Response'], [1, 5], [2, 6]]; // fewer rows than n_runs
    expect(() => extractResponse(values, d)).toThrow(/has \d+ runs/);
  });
});

describe('buildEffectsSheetRows', () => {
  it('matches the layout createEffectsChart expects', () => {
    const d = makeDesign();
    const response = d.matrix.map(row => (row.A as number) * 2 + (row.B as number) * -3);
    const result = analyze(d, response);
    const sheetData = buildEffectsSheetRows(result);
    expect(sheetData[0]).toEqual(['Term', 'Effect', 'SS', '% Contribution']);
    expect(sheetData).toHaveLength(result.effects.length + 1);
  });
});
