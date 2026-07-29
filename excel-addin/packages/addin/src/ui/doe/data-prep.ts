import { DOEDesign, DOEResult } from '@qikit/engine';

/** Pull the Response column out of a selected range (header row required); validates one value per run. */
export function extractResponse(values: any[][], design: DOEDesign): number[] {
  const headers = values[0] ?? [];
  const respIdx = headers.indexOf('Response');
  if (respIdx === -1) throw new Error("No 'Response' column found. Include headers in your selection.");
  const response = values.slice(1).map(row => row[respIdx]).filter(v => typeof v === 'number') as number[];
  if (response.length !== design.n_runs) {
    throw new Error(
      `The design has ${design.n_runs} runs but the selection contains ` +
      `${response.length} numeric response value${response.length === 1 ? '' : 's'}. ` +
      `Select the filled-in Response column (with its header) — one value per run.`
    );
  }
  return response;
}

/** Sheet layout consumed by createEffectsChart: Term(A), Effect(B), SS(C), % Contribution(D). */
export function buildEffectsSheetRows(result: DOEResult): any[][] {
  return [
    ['Term', 'Effect', 'SS', '% Contribution'],
    ...result.effects.map(e => [e.term, e.effect, e.ss, e.pct_contribution]),
  ];
}
