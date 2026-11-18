import { bchart } from '@qikit/engine';

export type BChartResult = ReturnType<typeof bchart>;

const isBlank = (v: unknown) => v === '' || v === null || v === undefined;

/** Numeric outcome values from the selected column. Throws when the column has no numbers,
 *  or has numbers other than 0 and 1. */
export function buildBChartValues(rawData: any[][], hasHeaders: boolean, xCol: number): number[] {
  const rows = hasHeaders ? rawData.slice(1) : rawData;
  const values = rows.filter(row => !isBlank(row[xCol])).map(row => Number(row[xCol])).filter(v => !isNaN(v));
  if (values.length === 0) throw new Error('No numeric values found in selected column.');
  const other = values.find(v => v !== 0 && v !== 1);
  if (other !== undefined) {
    const name = hasHeaders && !isBlank(rawData[0]?.[xCol]) ? `The "${rawData[0][xCol]}" column` : 'This column';
    throw new Error(
      `${name} has values other than 0 and 1 (such as ${other}). A Bernoulli CUSUM needs one ` +
      `outcome per case: 1 if the event happened, 0 if not. Choose that column under Data Column.`);
  }
  return values;
}

/** The first column holding only 0s and 1s (ignoring blanks), so an ID column before the
 *  outcomes is not chosen by default; 0 when there is none. */
export function firstBinaryColumn(rawData: any[][], hasHeaders: boolean): number {
  const rows = hasHeaders ? rawData.slice(1) : rawData;
  const width = Math.max(0, ...rawData.map(r => r.length));
  for (let c = 0; c < width; c++) {
    const cells = rows.map(r => r[c]).filter(v => !isBlank(v));
    if (cells.length > 0 && cells.every(v => v === 0 || v === 1 || v === '0' || v === '1')) return c;
  }
  return 0;
}

/** Sheet layout consumed by createBChartChart: Point(A), Value(B), CUSUM Up(C), CUSUM Down(D), Signal Up(E), Signal Down(F), Limit(G). */
export function buildBChartSheetRows(result: BChartResult): any[][] {
  return [
    ['Point', 'Value', 'CUSUM Up', 'CUSUM Down', 'Signal Up', 'Signal Down', 'Limit'],
    ...result.data.map((d: any) => [d.x, d.y, d.cusum_up, d.cusum_down, d.signal_up ? 1 : 0, d.signal_down ? 1 : 0, d.limit]),
  ];
}
