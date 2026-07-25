import { bchart } from '@qikit/engine';

export type BChartResult = ReturnType<typeof bchart>;

/** Numeric outcome values from the selected column. Throws when the column has no numbers. */
export function buildBChartValues(rawData: any[][], hasHeaders: boolean, xCol: number): number[] {
  const rows = hasHeaders ? rawData.slice(1) : rawData;
  const values = rows.map(row => Number(row[xCol])).filter(v => !isNaN(v));
  if (values.length === 0) throw new Error('No numeric values found in selected column.');
  return values;
}

/** Sheet layout consumed by createBChartChart: Point(A), Value(B), CUSUM Up(C), CUSUM Down(D), Signal Up(E), Signal Down(F), Limit(G). */
export function buildBChartSheetRows(result: BChartResult): any[][] {
  return [
    ['Point', 'Value', 'CUSUM Up', 'CUSUM Down', 'Signal Up', 'Signal Down', 'Limit'],
    ...result.data.map((d: any) => [d.x, d.y, d.cusum_up, d.cusum_down, d.signal_up ? 1 : 0, d.signal_down ? 1 : 0, d.limit]),
  ];
}
