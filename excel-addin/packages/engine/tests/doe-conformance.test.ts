import { describe, test, expect } from 'vitest';
import { globSync } from 'glob';
import { readFileSync } from 'fs';
import path from 'path';
import { design, analyze } from '../src';

const fixturePaths = globSync('../fixtures/experiment/*.json');

function experimentAnalyze(factors: string[], response: number[], kwargs: any) {
    const d = design({ factors, ...kwargs });
    return analyze(d, response);
}

const dispatch = { 
    experiment_design: (input: any) => design(input),
    experiment_analyze: (input: any) => {
        const { factors, response, ...rest } = input;
        return experimentAnalyze(factors, response, rest);
    }
};

function extract(result: any, key: string): any {
  if (key in result) return result[key];
  if (result.summary && key in result.summary) return result.summary[key];
  return undefined;
}

describe('DOE Conformance Tests', () => {
  fixturePaths.forEach(fixPath => {
    const fixture = JSON.parse(readFileSync(fixPath, 'utf-8'));
    const fn = (dispatch as any)[fixture.function];
    
    describe(`Fixture: ${fixture.id}`, () => {
      const result = fn(fixture.input);
      const dict = result.to_dict ? result.to_dict() : result;

      test('passes checks', () => {
        for (const [key, spec] of Object.entries(fixture.check)) {
          const actual = extract(result, key);
          if (Array.isArray(spec)) {
            expect(actual).toBeCloseTo(spec[0] as number, -Math.log10(spec[1] as number));
          } else {
            expect(actual).toEqual(spec);
          }
        }
      });

      test('matches snapshot', () => {
        const expected = fixture.snapshot;
        
        // Key fields
        ['n_runs', 'n_factors', 'grand_mean', 'r_squared', 'adj_r_squared'].forEach(field => {
            if (field in dict && field in expected) {
                if (typeof dict[field] === 'number') {
                    expect(dict[field]).toBeCloseTo(expected[field], 5);
                } else {
                    expect(dict[field]).toEqual(expected[field]);
                }
            }
        });

        // Matrix length
        if (dict.matrix && expected.matrix) {
            expect(dict.matrix.length).toEqual(expected.matrix.length);
        }
        
        // Effects match
        if (dict.effects && expected.effects) {
            expect(dict.effects.length).toEqual(expected.effects.length);
            dict.effects.forEach((eff: any, i: number) => {
                const expEff = expected.effects[i];
                expect(eff.term).toEqual(expEff.term);
                expect(eff.effect).toBeCloseTo(expEff.effect, 5);
            });
        }
      });
    });
  });
});
