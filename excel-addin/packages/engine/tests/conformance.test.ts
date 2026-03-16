import { describe, test, expect } from 'vitest';
import { globSync } from 'glob';
import { readFileSync } from 'fs';
import path from 'path';
import { compute, bchart, paretochart } from '../src';

const fixturePaths = globSync('../fixtures/spc/*.json');
const dispatch = { qic: compute, bchart, paretochart };

function extract(result: any, key: string): any {
  if (key === 'signals') return !!result.signals;
  if (key === 'target' || key === 'or_ratio' || key === 'limit') return result[key];
  if (key === 'ylab') return result.to_dict().ylab;
  
  // Data columns
  if (result.data && result.data.length > 0) {
    if (key in result.data[0]) return result.data[0][key];
  }
  
  // Summary
  if (result.summary && key in result.summary) return result.summary[key];
  
  return undefined;
}

describe('SPC Conformance Tests', () => {
  fixturePaths.forEach(fixPath => {
    const fixture = JSON.parse(readFileSync(fixPath, 'utf-8'));
    const fn = (dispatch as any)[fixture.function];
    
    describe(`Fixture: ${fixture.id}`, () => {
      let input = { ...fixture.input };
      if (input.data && typeof input.y === 'string') {
          // Resolve y from data column
          const colName = input.y;
          input.y = input.data[colName];
      }
      
      const result = fn(input);
      const dict = result.to_dict();

      test('passes checks', () => {
        for (const [key, spec] of Object.entries(fixture.check)) {
          const actual = extract(result, key);
          if (Array.isArray(spec)) {
            // spec is [value, tolerance]
            expect(actual).toBeCloseTo(spec[0] as number, -Math.log10(spec[1] as number));
          } else {
            expect(actual).toEqual(spec);
          }
        }
      });

      test('matches snapshot', () => {
        // Deep match excluding title, subtitle, caption, xlab, ylab which might differ slightly in defaults
        const expected = fixture.snapshot;
        expect(dict.chart_type).toEqual(expected.chart_type);
        expect(dict.method).toEqual(expected.method);
        expect(dict.signals).toEqual(expected.signals);
        
        // Match data rows (key columns)
        expect(dict.data.length).toEqual(expected.data.length);
        if (dict.data.length > 0) {
            dict.data.forEach((row: any, i: number) => {
                const expRow = expected.data[i];
                ['y', 'cl', 'ucl', 'lcl', 'sigma_signal', 'runs_signal'].forEach(col => {
                    if (col in row && col in expRow) {
                        if (typeof row[col] === 'number' && row[col] !== null) {
                            expect(row[col]).toBeCloseTo(expRow[col], 5);
                        } else {
                            expect(row[col]).toEqual(expRow[col]);
                        }
                    }
                });
            });
        }
      });
    });
  });
});
