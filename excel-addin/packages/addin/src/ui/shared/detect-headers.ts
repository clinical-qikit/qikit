import { colLetter } from './col-letter';

/** First-row header detection shared by the single-column panels (Pareto, B-chart). */
export function detectHeaderRow(rawData: any[][]): { hasHeaders: boolean; headers: string[] } {
  const firstRow = rawData[0] ?? [];
  const hasHeaders = firstRow.some((v: any) => typeof v === 'string' && String(v).trim() !== '');
  const headers = hasHeaders
    ? firstRow.map((h: any, i: number) => String(h || colLetter(i)))
    : firstRow.map((_: any, i: number) => colLetter(i));
  return { hasHeaders, headers };
}
