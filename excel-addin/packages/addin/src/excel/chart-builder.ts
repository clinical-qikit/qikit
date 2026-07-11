import { SPCResult, DOEResult } from '@qikit/engine';
import { qikit } from '../theme/tokens';

/* global Excel */

// Parse "Sheet1!A1:G50" → { sheet, firstRow, lastRow }
function parseAddress(sheetName: string, rangeAddress: string) {
  // rangeAddress may be "A1:G50" or "'Sheet1'!A1:G50"
  const bare = rangeAddress.includes('!') ? rangeAddress.split('!')[1] : rangeAddress;
  const [start, end] = bare.replace(/\$/g, '').split(':');
  const parseCell = (cell: string) => {
    const m = cell.match(/^([A-Z]+)(\d+)$/);
    if (!m) return { col: 'A', row: 1 };
    return { col: m[1], row: parseInt(m[2]) };
  };
  const s = parseCell(start);
  const e = parseCell(end ?? start);
  return { sheet: sheetName, firstRow: s.row, lastRow: e.row };
}

// ─── SPC Chart ────────────────────────────────────────────────────────────────
// Sheet layout: Point(A), Value(B), CL(C), UCL(D), LCL(E), Signal(F), [Note(G)]
// Signal column contains 1 or null — used as scatter overlay

export async function createSPCChart(result: SPCResult, sheetName: string, rangeAddress: string): Promise<void> {
  await Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.getItem(sheetName);
    const info = parseAddress(sheetName, rangeAddress);
    const firstRow = info.firstRow + 1; // skip header
    const lastRow = info.lastRow;

    // Create an empty line chart and add series manually
    const emptyRange = sheet.getRange(`A${firstRow}:A${firstRow}`);
    const chart = sheet.charts.add(Excel.ChartType.line, emptyRange, Excel.ChartSeriesBy.columns);

    // Remove the auto-added default series
    chart.series.getItemAt(0).delete();

    // Helper to add a series
    const addSeries = (name: string, col: string): Excel.ChartSeries => {
      const s = chart.series.add(name);
      s.setValues(sheet.getRange(`${col}${firstRow}:${col}${lastRow}`));
      s.setXAxisValues(sheet.getRange(`A${firstRow}:A${lastRow}`));
      return s;
    };

    // Series 0: Value (solid dark line)
    const valueSeries = addSeries('Value', 'B');
    valueSeries.format.line.color = qikit.chart.data;
    valueSeries.markerStyle = Excel.ChartMarkerStyle.circle;
    valueSeries.markerSize = 4;
    valueSeries.markerForegroundColor = qikit.chart.data;
    valueSeries.markerBackgroundColor = qikit.chart.data;

    // Series 1: CL (dashed gray)
    const clSeries = addSeries('CL', 'C');
    clSeries.format.line.color = qikit.chart.limit;
    (clSeries.format.line as any).dashStyle = (Excel as any).ChartLineDashStyle.dash;
    clSeries.markerStyle = Excel.ChartMarkerStyle.none;

    // Series 2: UCL (solid gray)
    const uclSeries = addSeries('UCL', 'D');
    uclSeries.format.line.color = qikit.chart.limit;
    uclSeries.markerStyle = Excel.ChartMarkerStyle.none;

    // Series 3: LCL (solid gray)
    const lclSeries = addSeries('LCL', 'E');
    lclSeries.format.line.color = qikit.chart.limit;
    lclSeries.markerStyle = Excel.ChartMarkerStyle.none;

    // Chart title
    const chartTypeName = result.chart_type.toUpperCase();
    chart.title.text = `SPC — ${chartTypeName} Chart`;
    chart.title.format.font.size = 13;
    chart.title.format.font.bold = true;
    chart.title.format.font.color = qikit.chart.data;

    // Axis titles
    chart.axes.valueAxis.title.text = 'Value';
    chart.axes.valueAxis.title.format.font.size = 11;
    chart.axes.categoryAxis.title.text = 'Point';
    chart.axes.categoryAxis.title.format.font.size = 11;

    // Legend
    chart.legend.visible = true;
    chart.legend.position = Excel.ChartLegendPosition.bottom;

    // Size and position
    chart.top = 20;
    chart.left = 400;
    chart.width = 620;
    chart.height = 360;

    await context.sync();
  });
}

// ─── DOE Effects Chart ────────────────────────────────────────────────────────
// Sheet layout: Term(A), Effect(B), SS(C), % Contribution(D)
// Horizontal bar chart: A (labels) vs B (effect magnitude)

export async function createEffectsChart(result: DOEResult, sheetName: string, rangeAddress: string): Promise<void> {
  await Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.getItem(sheetName);
    const info = parseAddress(sheetName, rangeAddress);
    const firstRow = info.firstRow + 1;
    const lastRow = info.lastRow;

    const emptyRange = sheet.getRange(`A${firstRow}:A${firstRow}`);
    const chart = sheet.charts.add(Excel.ChartType.barClustered, emptyRange, Excel.ChartSeriesBy.columns);
    chart.series.getItemAt(0).delete();

    const effectSeries = chart.series.add('Effect');
    effectSeries.setValues(sheet.getRange(`B${firstRow}:B${lastRow}`));
    effectSeries.setXAxisValues(sheet.getRange(`A${firstRow}:A${lastRow}`));
    effectSeries.format.fill.setSolidColor(qikit.chart.brand);

    chart.title.text = `DOE Effects  (R²=${(result.r_squared * 100).toFixed(1)}%)`;
    chart.title.format.font.size = 13;
    chart.title.format.font.bold = true;
    chart.title.format.font.color = qikit.chart.data;

    chart.axes.valueAxis.title.text = 'Effect';
    chart.axes.valueAxis.title.format.font.size = 11;
    (chart.axes.valueAxis as any).crossesAt = 0;

    chart.legend.visible = false;

    chart.top = 20;
    chart.left = 300;
    chart.width = 520;
    chart.height = Math.max(200, 60 + result.effects.length * 28);

    await context.sync();
  });
}

// ─── Pareto Chart ─────────────────────────────────────────────────────────────
// Sheet layout: Category(A), Count(B), Cumulative Sum(C), Cumulative %(D)
// Combo: bars for Count (primary y) + line for Cumulative % (secondary y)

export async function createParetoChart(_result: any, sheetName: string, rangeAddress: string): Promise<void> {
  await Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.getItem(sheetName);
    const info = parseAddress(sheetName, rangeAddress);
    const firstRow = info.firstRow + 1;
    const lastRow = info.lastRow;

    // Create combo chart: use column chart type as base
    const emptyRange = sheet.getRange(`A${firstRow}:A${firstRow}`);
    const chart = sheet.charts.add(Excel.ChartType.columnClustered, emptyRange, Excel.ChartSeriesBy.columns);
    chart.series.getItemAt(0).delete();

    // Series 0: Count bars (primary axis)
    const countSeries = chart.series.add('Count');
    countSeries.setValues(sheet.getRange(`B${firstRow}:B${lastRow}`));
    countSeries.setXAxisValues(sheet.getRange(`A${firstRow}:A${lastRow}`));
    countSeries.format.fill.setSolidColor(qikit.chart.brand);
    countSeries.chartType = Excel.ChartType.columnClustered;

    // Series 1: Cumulative % line (secondary axis)
    const cumSeries = chart.series.add('Cumulative %');
    cumSeries.setValues(sheet.getRange(`D${firstRow}:D${lastRow}`));
    cumSeries.setXAxisValues(sheet.getRange(`A${firstRow}:A${lastRow}`));
    cumSeries.chartType = Excel.ChartType.line;
    cumSeries.format.line.color = qikit.chart.accent;
    cumSeries.markerStyle = Excel.ChartMarkerStyle.circle;
    cumSeries.markerSize = 4;
    cumSeries.axisGroup = Excel.ChartAxisGroup.secondary;

    // Axes
    chart.axes.valueAxis.title.text = 'Frequency';
    chart.axes.valueAxis.title.format.font.size = 11;
    chart.axes.seriesAxis.title.text = 'Cumulative %';
    chart.axes.seriesAxis.title.format.font.size = 11;

    chart.title.text = 'Pareto Chart';
    chart.title.format.font.size = 13;
    chart.title.format.font.bold = true;
    chart.title.format.font.color = qikit.chart.data;

    chart.legend.visible = true;
    chart.legend.position = Excel.ChartLegendPosition.bottom;

    chart.top = 20;
    chart.left = 300;
    chart.width = 560;
    chart.height = 360;

    await context.sync();
  });
}

// ─── Bernoulli CUSUM Chart ────────────────────────────────────────────────────
// Sheet layout: Point(A), Value(B), CUSUM Up(C), CUSUM Down(D), Signal Up(E), Signal Down(F), Limit(G)

export async function createBChartChart(_result: any, sheetName: string, rangeAddress: string): Promise<void> {
  await Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.getItem(sheetName);
    const info = parseAddress(sheetName, rangeAddress);
    const firstRow = info.firstRow + 1;
    const lastRow = info.lastRow;

    const emptyRange = sheet.getRange(`A${firstRow}:A${firstRow}`);
    const chart = sheet.charts.add(Excel.ChartType.line, emptyRange, Excel.ChartSeriesBy.columns);
    chart.series.getItemAt(0).delete();

    // CUSUM Up — solid brand teal
    const upSeries = chart.series.add('CUSUM Up');
    upSeries.setValues(sheet.getRange(`C${firstRow}:C${lastRow}`));
    upSeries.setXAxisValues(sheet.getRange(`A${firstRow}:A${lastRow}`));
    upSeries.format.line.color = qikit.chart.brand;
    upSeries.markerStyle = Excel.ChartMarkerStyle.none;

    // CUSUM Down — dashed slate
    const downSeries = chart.series.add('CUSUM Down');
    downSeries.setValues(sheet.getRange(`D${firstRow}:D${lastRow}`));
    downSeries.setXAxisValues(sheet.getRange(`A${firstRow}:A${lastRow}`));
    downSeries.format.line.color = qikit.chart.limit;
    (downSeries.format.line as any).dashStyle = (Excel as any).ChartLineDashStyle.dash;
    downSeries.markerStyle = Excel.ChartMarkerStyle.none;

    // Limit line (positive) — dashed orange
    const limitSeries = chart.series.add('+Limit');
    limitSeries.setValues(sheet.getRange(`G${firstRow}:G${lastRow}`));
    limitSeries.setXAxisValues(sheet.getRange(`A${firstRow}:A${lastRow}`));
    limitSeries.format.line.color = qikit.chart.accent;
    (limitSeries.format.line as any).dashStyle = (Excel as any).ChartLineDashStyle.dot;
    limitSeries.markerStyle = Excel.ChartMarkerStyle.none;

    chart.title.text = 'Bernoulli CUSUM';
    chart.title.format.font.size = 13;
    chart.title.format.font.bold = true;
    chart.title.format.font.color = qikit.chart.data;

    chart.axes.valueAxis.title.text = 'CUSUM Statistic';
    chart.axes.valueAxis.title.format.font.size = 11;
    chart.axes.categoryAxis.title.text = 'Point';
    chart.axes.categoryAxis.title.format.font.size = 11;

    chart.legend.visible = true;
    chart.legend.position = Excel.ChartLegendPosition.bottom;

    chart.top = 20;
    chart.left = 400;
    chart.width = 600;
    chart.height = 340;

    await context.sync();
  });
}
