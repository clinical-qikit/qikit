import { paretochart } from '@qikit/engine';

export type ParetoResult = ReturnType<typeof paretochart>;

/** Category strings from the selected column. Throws when the column is empty. */
export function buildParetoValues(rawData: any[][], hasHeaders: boolean, xCol: number): string[] {
  const rows = hasHeaders ? rawData.slice(1) : rawData;
  const values = rows.map(row => String(row[xCol] ?? '')).filter(v => v !== '' && v !== 'null');
  if (values.length === 0) throw new Error('No values found in selected column.');
  return values;
}

/** Sheet layout consumed by createParetoChart: Category(A), Count(B), Cumulative Sum(C), Cumulative %(D). */
export function buildParetoSheetRows(result: ParetoResult): any[][] {
  return [
    ['Category', 'Count', 'Cumulative Sum', 'Cumulative %'],
    ...result.data.map((d: any) => [d.category, d.count, d.cum_sum, d.cum_percent]),
  ];
}
