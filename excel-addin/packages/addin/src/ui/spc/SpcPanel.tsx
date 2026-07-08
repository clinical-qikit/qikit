import React, { useState, useEffect, useCallback } from 'react';
import { Button, Checkbox } from '@fluentui/react-components';
import {
  ChevronDownRegular, ChevronRightRegular,
  ArrowSyncRegular, SettingsRegular,
  ArrowDownloadRegular, DocumentRegular,
} from '@fluentui/react-icons';
import { ChartType, compute, SPCResult } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import { ChartViewer } from '../shared/ChartViewer';
import { DataPreview } from '../shared/DataPreview';
import { useSpcStyles } from './styles';
import { NEEDS_SUBGROUP, SpcOptions, DEFAULT_OPTIONS, DataGrain } from './constants';
import { parseColumns, buildSpcInput, buildNoteMap, buildSheetRows, SpcDataSelection } from './data-prep';
import { ChartTypePicker } from './ChartTypePicker';
import { ColumnSelector } from './ColumnSelector';
import { SignalMethodPicker } from './SignalMethodPicker';
import { LimitOptions } from './LimitOptions';
import { AnnotationBar, AnnotationList } from './AnnotationEditor';
import { SummaryPanel } from './SummaryPanel';

export const SpcPanel: React.FC = () => {
  const styles = useSpcStyles();

  // Data
  const [rangeAddress, setRangeAddress] = useState<string | null>(null);
  const [rawData, setRawData] = useState<any[][]>([]);
  const [hasHeaders, setHasHeaders] = useState(false);
  const [headers, setHeaders] = useState<string[]>([]);
  const [numericCols, setNumericCols] = useState<number[]>([]);
  const [dateCols, setDateCols] = useState<number[]>([]);
  const [yCol, setYCol] = useState<number>(0);
  const [nCol, setNCol] = useState<number | null>(null);
  const [dataGrain, setDataGrain] = useState<DataGrain>('summarized');
  const [xCol, setXCol] = useState<number | null>(null);
  const [notesCol, setNotesCol] = useState<number | null>(null);

  // Date aggregation
  const [xPeriod, setXPeriod] = useState<string>('month');

  // Chart
  const [chartType, setChartType] = useState<ChartType>('run');
  const [result, setResult] = useState<SPCResult | null>(null);

  // Annotations
  const [annotations, setAnnotations] = useState<Record<number, string>>({});
  const [activeAnnotIdx, setActiveAnnotIdx] = useState<number | null>(null);

  // UI
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [includeDataTable, setIncludeDataTable] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Options
  const [options, setOptions] = useState<SpcOptions>(DEFAULT_OPTIONS);
  const patchOptions = useCallback((patch: Partial<SpcOptions>) =>
    setOptions(o => ({ ...o, ...patch })), []);

  // Parse columns when data loaded
  useEffect(() => {
    if (rawData.length === 0) return;
    const parsed = parseColumns(rawData);
    setHasHeaders(parsed.hasHeaders);
    setHeaders(parsed.headers);
    setNumericCols(parsed.numericCols);
    setDateCols(parsed.dateCols);
    if (parsed.numericCols.length > 0) setYCol(parsed.numericCols[0]);
    setNCol(null);
    setNotesCol(null);
    // Auto-select first date or label col as X
    const firstDate = parsed.dateCols[0] ?? null;
    const firstLabel = parsed.labelCols[0] ?? null;
    setXCol(firstDate ?? firstLabel ?? null);
  }, [rawData]);

  // Auto-compute
  useEffect(() => {
    if (rawData.length < 2) {
      setResult(null);
      return;
    }
    setError(null);
    try {
      const selection: SpcDataSelection = {
        rawData, hasHeaders, dateCols, xCol, yCol, nCol, notesCol,
        chartType, dataGrain, xPeriod, options,
      };
      const prepared = buildSpcInput(selection);

      if (!prepared) {
        setError('No numeric data in selected column.');
        setResult(null);
        return;
      }

      const res = compute(prepared.input);

      // Attach xLabels and partLabels to result for ChartViewer
      (res as any)._xLabels = prepared.xLabels;
      (res as any)._partBoundaries = prepared.input.part;
      (res as any)._partLabels = prepared.partLabels;

      setResult(res);

      // Notes from data column
      if (notesCol !== null) {
        const noteMap = buildNoteMap(selection);
        setAnnotations(prev => ({ ...noteMap, ...prev }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Computation failed.');
      setResult(null);
    }
  }, [rawData, hasHeaders, chartType, yCol, nCol, xCol, notesCol, xPeriod, options, dateCols, dataGrain]);

  const handleSelectData = useCallback(async () => {
    setError(null);
    try {
      const res = await getSelectedRangeValues();
      setRawData(res.values);
      setRangeAddress(res.address);
      setAnnotations({});
      setActiveAnnotIdx(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to read selection.');
    }
  }, []);

  const handlePointClick = useCallback((idx: number) => {
    setActiveAnnotIdx(idx);
  }, []);

  const handleSaveAnnotation = useCallback((idx: number, text: string) => {
    setAnnotations(a => {
      const next = { ...a };
      if (text.trim()) next[idx] = text.trim();
      else delete next[idx];
      return next;
    });
    setActiveAnnotIdx(null);
  }, []);

  const handleRemoveAnnotation = useCallback((idx: number) => {
    setAnnotations(a => { const next = { ...a }; delete next[idx]; return next; });
  }, []);

  const handleWriteToSheet = useCallback(async () => {
    if (!result) return;
    setError(null);
    try {
      const { finalCols, rows } = buildSheetRows(
        result, annotations, rawData, hasHeaders, headers, includeDataTable,
      );
      const sheetLabel = `SPC ${result.chart_type.toUpperCase()}`;
      const { sheetName, rangeAddress: ra } = await writeToNewSheet(sheetLabel, [finalCols, ...rows]);
      const { createSPCChart } = await import('../../excel/chart-builder');
      await createSPCChart(result, sheetName, ra);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to write to sheet.');
    }
  }, [result, annotations, rawData, hasHeaders, headers, includeDataTable]);

  const needsSubgroup = NEEDS_SUBGROUP.includes(chartType);
  const hasData = rawData.length > 1;
  const target = options.target ? parseFloat(options.target) : undefined;
  const isDateX = xCol !== null && dateCols.includes(xCol);
  const xLabels = (result as any)?._xLabels as string[] | undefined;
  const partBoundaries = (result as any)?._partBoundaries as number[] | undefined;
  const partLabels = (result as any)?._partLabels as string[] | undefined;

  return (
    <div className={styles.panel}>
      {/* ── Data source ── */}
      {!rangeAddress ? (
        <div className={styles.dataSourceEmpty}>
          <div className={styles.dataSourceIcon}><DocumentRegular /></div>
          <Button appearance="primary" size="medium" onClick={handleSelectData}
            style={{ borderRadius: '6px', minWidth: '180px', backgroundColor: '#107C6C', borderColor: '#0A6B5C' }}>
            Use Current Selection
          </Button>
          <span className={styles.dataSourceHint}>Select a data range in Excel, then click above</span>
        </div>
      ) : (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Data Source</div>
          <div className={styles.dataSourceBar}>
            <span className={styles.address}>{rangeAddress}</span>
            <Button size="small" icon={<ArrowSyncRegular />} appearance="subtle"
              onClick={handleSelectData} title="Re-read selection" style={{ borderRadius: '6px' }} />
          </div>
          {hasData && (
            <button className={styles.settingsToggle} onClick={() => setPreviewOpen(o => !o)}
              style={{ marginTop: '8px' }}>
              {previewOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
              Data preview
            </button>
          )}
          {previewOpen && hasData && (
            <div style={{ marginTop: '8px' }}>
              <DataPreview data={rawData} hasHeaders={hasHeaders} />
            </div>
          )}
        </div>
      )}

      {/* ── Chart type ── */}
      {hasData && <ChartTypePicker chartType={chartType} onChange={setChartType} />}

      {/* ── Column mapping ── */}
      {hasData && (
        <ColumnSelector
          headers={headers}
          numericCols={numericCols}
          chartType={chartType}
          dataGrain={dataGrain}
          xCol={xCol} yCol={yCol} nCol={nCol} notesCol={notesCol}
          isDateX={isDateX}
          xPeriod={xPeriod}
          onDataGrainChange={setDataGrain}
          onXColChange={setXCol}
          onYColChange={setYCol}
          onNColChange={setNCol}
          onNotesColChange={setNotesCol}
          onXPeriodChange={setXPeriod}
        />
      )}

      {/* ── Settings ── */}
      {hasData && (
        <div className={styles.section}>
          <button className={styles.settingsToggle} onClick={() => setSettingsOpen(o => !o)}>
            <SettingsRegular style={{ fontSize: '14px' }} />
            Settings
            {settingsOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
          </button>

          {settingsOpen && (
            <div className={styles.settingsPanel}>
              <SignalMethodPicker value={options.method} onChange={method => patchOptions({ method })} />
              <LimitOptions options={options} needsSubgroup={needsSubgroup} onChange={patchOptions} />
            </div>
          )}
        </div>
      )}

      {/* ── Error ── */}
      {error && <div className={styles.error}>{error}</div>}

      {/* ── Chart ── */}
      {result ? (
        <>
          <div style={{ padding: '8px 16px 0' }}>
            <ChartViewer
              result={result}
              type="spc"
              annotations={annotations}
              onPointClick={handlePointClick}
              target={target}
              xLabels={xLabels}
              show95={options.show95}
              partBoundaries={partBoundaries}
              partLabels={partLabels}
              chartType={chartType}
            />
          </div>

          {activeAnnotIdx !== null && (
            <AnnotationBar
              key={activeAnnotIdx}
              pointIdx={activeAnnotIdx}
              initialText={annotations[activeAnnotIdx] || ''}
              onSave={handleSaveAnnotation}
              onCancel={() => setActiveAnnotIdx(null)}
            />
          )}

          <AnnotationList annotations={annotations} onRemove={handleRemoveAnnotation} />

          <SummaryPanel result={result} />

          {/* Write actions */}
          <div className={styles.actions}>
            <Checkbox label="Include source data" checked={includeDataTable}
              onChange={(_, d) => setIncludeDataTable(!!d.checked)} />
            <Button appearance="primary" icon={<ArrowDownloadRegular />}
              onClick={handleWriteToSheet} style={{ borderRadius: '6px', backgroundColor: '#107C6C', borderColor: '#0A6B5C' }}>
              Write to Sheet
            </Button>
          </div>
        </>
      ) : hasData ? (
        <div className={styles.emptyChart}>Computing chart…</div>
      ) : null}
    </div>
  );
};
