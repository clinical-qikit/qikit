import { SPCResult, DOEResult } from '@qikit/engine';

/* global Excel */

export async function createSPCChart(result: SPCResult, sheetName: string, rangeAddress: string): Promise<void> {
  await Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.getItem(sheetName);
    const range = sheet.getRange(rangeAddress);
    
    // Add a line chart
    const chart = sheet.charts.add(Excel.ChartType.line, range, Excel.ChartSeriesBy.columns);
    chart.title.text = `SPC Chart - ${result.chart_type.toUpperCase()}`;
    chart.title.format.font.size = 14;
    chart.title.format.font.bold = true;
    
    // Position the chart to the right of the data
    chart.top = 20;
    chart.left = 400; 
    chart.width = 600;
    chart.height = 350;

    await context.sync();
  });
}

export async function createEffectsChart(result: DOEResult, sheetName: string, rangeAddress: string): Promise<void> {
  await Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.getItem(sheetName);
    const range = sheet.getRange(rangeAddress);
    
    // Create a Bar chart (clustered bar or column)
    const chart = sheet.charts.add(Excel.ChartType.barClustered, range, Excel.ChartSeriesBy.columns);
    chart.title.text = `DOE Effects`;
    chart.title.format.font.size = 14;
    chart.title.format.font.bold = true;

    chart.top = 20;
    chart.left = 300;
    chart.width = 500;
    chart.height = 300;

    await context.sync();
  });
}
