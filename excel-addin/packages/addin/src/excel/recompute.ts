import { compute, paretochart, bchart, analyze, ChartType, DOEDesign } from '@qikit/engine';
import { parseColumns, buildSpcInput, buildSheetRows, SpcDataSelection } from '../ui/spc/data-prep';
import { SpcOptions, DataGrain } from '../ui/spc/constants';
import { detectHeaderRow } from '../ui/shared/detect-headers';
import { buildParetoValues, buildParetoSheetRows } from '../ui/pareto/data-prep';
import { buildBChartValues, buildBChartSheetRows } from '../ui/bchart/data-prep';
import { extractResponse, buildEffectsSheetRows } from '../ui/doe/data-prep';
import { createSPCChart, createParetoChart, createBChartChart, createEffectsChart } from './chart-builder';

export type PanelKind = 'spc' | 'pareto' | 'bchart' | 'doe';

export interface SpcLiveConfig {
  xCol: number | null;
  yCol: number;
  nCol: number | null;
  notesCol: number | null;
  chartType: ChartType;
  dataGrain: DataGrain;
  xPeriod: string;
  options: SpcOptions;
  includeDataTable: boolean;
  annotations: Record<number, string>;
}

export interface ParetoLiveConfig {
  xCol: number;
}

export interface BChartLiveConfig {
  xCol: number;
  target?: number;
  orRatio: number;
  limit: number;
}

export interface DoeLiveConfig {
  design: DOEDesign;
}

export type LiveConfig = SpcLiveConfig | ParetoLiveConfig | BChartLiveConfig | DoeLiveConfig;

export interface RecomputeOutcome {
  sheetData: any[][];
  writeChart: (sheetName: string, rangeAddress: string) => Promise<void>;
}

/** Re-runs the engine for the given panel and produces the new sheet table plus a chart writer. */
export function recompute(panel: PanelKind, values: any[][], config: LiveConfig): RecomputeOutcome {
  switch (panel) {
    case 'spc': {
      const cfg = config as SpcLiveConfig;
      const parsed = parseColumns(values);
      const selection: SpcDataSelection = {
        rawData: values, hasHeaders: parsed.hasHeaders, dateCols: parsed.dateCols,
        xCol: cfg.xCol, yCol: cfg.yCol, nCol: cfg.nCol, notesCol: cfg.notesCol,
        chartType: cfg.chartType, dataGrain: cfg.dataGrain, xPeriod: cfg.xPeriod, options: cfg.options,
      };
      const prepared = buildSpcInput(selection);
      if (!prepared) throw new Error('No numeric data in selected column.');
      const result = compute(prepared.input);
      const { finalCols, rows } = buildSheetRows(
        result, cfg.annotations, values, parsed.hasHeaders, parsed.headers, cfg.includeDataTable,
      );
      const sheetData = [finalCols, ...rows];
      return { sheetData, writeChart: (sheetName, ra) => createSPCChart(result, sheetName, ra) };
    }
    case 'pareto': {
      const cfg = config as ParetoLiveConfig;
      const { hasHeaders } = detectHeaderRow(values);
      const xs = buildParetoValues(values, hasHeaders, cfg.xCol);
      const result = paretochart({ x: xs });
      const sheetData = buildParetoSheetRows(result);
      return { sheetData, writeChart: (sheetName, ra) => createParetoChart(result, sheetName, ra) };
    }
    case 'bchart': {
      const cfg = config as BChartLiveConfig;
      const { hasHeaders } = detectHeaderRow(values);
      const xs = buildBChartValues(values, hasHeaders, cfg.xCol);
      const result = bchart({ x: xs, target: cfg.target, or_ratio: cfg.orRatio, limit: cfg.limit });
      const sheetData = buildBChartSheetRows(result);
      return { sheetData, writeChart: (sheetName, ra) => createBChartChart(result, sheetName, ra) };
    }
    case 'doe': {
      const cfg = config as DoeLiveConfig;
      const response = extractResponse(values, cfg.design);
      const result = analyze(cfg.design, response);
      const sheetData = buildEffectsSheetRows(result);
      return { sheetData, writeChart: (sheetName, ra) => createEffectsChart(result, sheetName, ra) };
    }
    default: {
      const _exhaustive: never = panel;
      throw new Error(`Unknown panel kind: ${_exhaustive}`);
    }
  }
}
