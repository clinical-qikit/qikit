import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Button, Checkbox, Spinner } from '@fluentui/react-components';
import {
  ChevronDownRegular, ChevronRightRegular,
  ArrowSyncRegular, SettingsRegular,
  ArrowDownloadRegular, DocumentRegular,
} from '@fluentui/react-icons';
import { ChartType, compute, SPCResult } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet, writeSampleSheet, RangeData } from '../../excel/excel-io';
import { registerLiveUpdate } from '../../excel/live-update';
import { ChartViewer } from '../shared/ChartViewer';
import { DataPreview } from '../shared/DataPreview';
import { LiveUpdateStatus, useLiveUpdateStatus } from '../shared/LiveUpdateStatus';
import { useSpcStyles } from './styles';
import { NEEDS_N, NEEDS_SUBGROUP, SpcOptions, DEFAULT_OPTIONS, DataGrain } from './constants';
import {
  parseColumns, buildSpcInput, buildNoteMap, buildSheetRows, SpcDataSelection,
  SkippedRow, inferPeriod, toDate,
} from './data-prep';
import { describeFindings, Findings } from './findings';
import { FindingsPanel } from './FindingsPanel';
import { loadSpcSettings, saveSpcSettings } from './remembered';
import { sampleRows, SAMPLE_FORMATS, SAMPLE_SHEET_NAME } from './sample-data';
import { ChartTypePicker } from './ChartTypePicker';
import { ColumnSelector } from './ColumnSelector';
import { SignalMethodPicker } from './SignalMethodPicker';
import { LimitOptions } from './LimitOptions';
import { AnnotationBar, AnnotationList } from './AnnotationEditor';
import { SummaryPanel } from './SummaryPanel';
import { ErrorNotice } from '../shared/ErrorNotice';
import { ErrorState, panelError } from '../shared/error-report';

export const SpcPanel: React.FC = () => {
  const styles = useSpcStyles();
  // What this workbook remembers from last time (chart type, grain, options).
  const [remembered] = useState(loadSpcSettings);

  // Data
  const [rangeAddress, setRangeAddress] = useState<string | null>(null);
  const [rawData, setRawData] = useState<any[][]>([]);
  const [numberFormats, setNumberFormats] = useState<any[][] | undefined>(undefined);
  const [firstRow, setFirstRow] = useState(1);
  const [hasHeaders, setHasHeaders] = useState(false);
  const [headers, setHeaders] = useState<string[]>([]);
  const [numericCols, setNumericCols] = useState<number[]>([]);
  const [dateCols, setDateCols] = useState<number[]>([]);
  const [yCol, setYCol] = useState<number>(0);
  const [nCol, setNCol] = useState<number | null>(null);
  const [dataGrain, setDataGrain] = useState<DataGrain>(remembered?.dataGrain ?? 'summarized');
  const [xCol, setXCol] = useState<number | null>(null);
  const [notesCol, setNotesCol] = useState<number | null>(null);

  // Date aggregation
  const [xPeriod, setXPeriod] = useState<string>('month');

  // Chart
  const [chartType, setChartType] = useState<ChartType>(remembered?.chartType ?? 'run');
  const [result, setResult] = useState<SPCResult | null>(null);
  const [findings, setFindings] = useState<Findings | null>(null);
  const [skipped, setSkipped] = useState<SkippedRow[]>([]);

  // Annotations
  const [annotations, setAnnotations] = useState<Record<number, string>>({});
  const [activeAnnotIdx, setActiveAnnotIdx] = useState<number | null>(null);

  // UI
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [includeDataTable, setIncludeDataTable] = useState(remembered?.includeDataTable ?? false);
  const [isWriting, setIsWriting] = useState(false);
  const [isLoadingSample, setIsLoadingSample] = useState(false);
  const [error, setError] = useState<ErrorState>(null);
  const liveUpdate = useLiveUpdateStatus();

  // Options
  const [options, setOptions] = useState<SpcOptions>(remembered?.options ?? DEFAULT_OPTIONS);
  const patchOptions = useCallback((patch: Partial<SpcOptions>) =>
    setOptions(o => ({ ...o, ...patch })), []);

  // Remember the choices in this workbook, once the user changes one: writing on
  // first render would mark every workbook the pane opens in as changed.
  const settingsTouched = useRef(false);
  useEffect(() => {
    if (!settingsTouched.current) { settingsTouched.current = true; return; }
    saveSpcSettings({ chartType, dataGrain, options, includeDataTable });
  }, [chartType, dataGrain, options, includeDataTable]);

  // Parse columns when data loaded
  useEffect(() => {
    if (rawData.length === 0) return;
    const parsed = parseColumns(rawData, numberFormats);
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
    // Daily data stays daily, monthly stays monthly.
    if (firstDate !== null) {
      const rows = parsed.hasHeaders ? rawData.slice(1) : rawData;
      setXPeriod(inferPeriod(rows.map(r => toDate(r[firstDate]))));
    }
  }, [rawData, numberFormats]);

  // Auto-compute
  useEffect(() => {
    if (rawData.length < 2) {
      setResult(null);
      setFindings(null);
      setSkipped([]);
      return;
    }
    setError(null);
    // An attribute chart needs its denominator column chosen; say which box to fill
    // rather than show the engine's error.
    if (NEEDS_N.includes(chartType) && nCol === null && dataGrain !== 'individual') {
      const box = ['u', 'up'].includes(chartType) ? 'Exposure' : 'Sample size';
      setError(`A ${chartType.toUpperCase()} chart divides each count by a denominator: ` +
        `choose that column in the ${box} box above.`);
      setResult(null);
      setFindings(null);
      setSkipped([]);
      return;
    }
    try {
      const selection: SpcDataSelection = {
        rawData, hasHeaders, dateCols, xCol, yCol, nCol, notesCol,
        chartType, dataGrain, xPeriod, options, firstRow,
      };
      const prepared = buildSpcInput(selection);

      if (!prepared) {
        setError(`No usable rows: the ${headers[yCol] ?? 'value'} column has no numbers` +
          (nCol !== null ? ', or no row has a usable denominator.' : '.'));
        setResult(null);
        setFindings(null);
        setSkipped([]);
        return;
      }

      const res = compute(prepared.input);

      // Attach xLabels and partLabels to result for ChartViewer
      (res as any)._xLabels = prepared.xLabels;
      (res as any)._partBoundaries = prepared.input.part;
      (res as any)._partLabels = prepared.partLabels;
      (res as any)._pointRows = prepared.pointRows;

      setResult(res);
      setSkipped(prepared.skipped);
      setFindings(describeFindings(res, {
        xLabels: prepared.xLabels, freeze: prepared.input.freeze,
        part: typeof prepared.input.part === 'number' ? [prepared.input.part] : prepared.input.part,
      }));

      // Notes from data column
      if (notesCol !== null) {
        const noteMap = buildNoteMap(selection, prepared.pointRows);
        setAnnotations(prev => ({ ...noteMap, ...prev }));
      }
    } catch (err) {
      setError(panelError(err, 'Computation failed.'));
      setResult(null);
      setFindings(null);
    }
  }, [rawData, hasHeaders, headers, chartType, yCol, nCol, xCol, notesCol, xPeriod, options, dateCols, dataGrain, firstRow]);

  const loadRange = useCallback((res: RangeData) => {
    setRawData(res.values);
    setNumberFormats(res.numberFormats);
    setFirstRow(res.firstRow);
    setRangeAddress(res.address);
    setAnnotations({});
    setActiveAnnotIdx(null);
  }, []);

  const handleSelectData = useCallback(async () => {
    setError(null);
    try {
      loadRange(await getSelectedRangeValues());
    } catch (err) {
      setError(panelError(err, 'Failed to read selection.'));
    }
  }, [loadRange]);

  const handleSampleData = useCallback(async () => {
    setError(null);
    setIsLoadingSample(true);
    try {
      loadRange(await writeSampleSheet(SAMPLE_SHEET_NAME, sampleRows(), SAMPLE_FORMATS));
    } catch (err) {
      setError(panelError(err, 'Failed to write the sample data.'));
    } finally {
      setIsLoadingSample(false);
    }
  }, [loadRange]);

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
    if (!result || !rangeAddress) return;
    setError(null);
    setIsWriting(true);
    try {
      const { finalCols, rows } = buildSheetRows(
        result, annotations, rawData, hasHeaders, headers, includeDataTable,
        (result as any)._pointRows,
      );
      const sheetData = [finalCols, ...rows];
      const sheetLabel = `SPC ${result.chart_type.toUpperCase()}`;
      const { sheetName, rangeAddress: ra } = await writeToNewSheet(sheetLabel, sheetData);
      const { createSPCChart } = await import('../../excel/chart-builder');
      await createSPCChart(result, sheetName, ra);
      const bindingId = await registerLiveUpdate({
        panel: 'spc',
        sourceAddress: rangeAddress,
        outputSheet: sheetName,
        outputRowCount: sheetData.length,
        config: {
          xCol, yCol, nCol, notesCol, chartType, dataGrain, xPeriod, options,
          includeDataTable, annotations,
        },
      });
      liveUpdate.activate(bindingId, rangeAddress);
    } catch (err) {
      setError(panelError(err, 'Failed to write to sheet.'));
    } finally {
      setIsWriting(false);
    }
  }, [
    result, rangeAddress, annotations, rawData, hasHeaders, headers, includeDataTable,
    xCol, yCol, nCol, notesCol, chartType, dataGrain, xPeriod, options, liveUpdate.activate,
  ]);

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
            style={{ borderRadius: '6px', minWidth: '180px' }}>
            Use Current Selection
          </Button>
          <span className={styles.dataSourceHint}>
            Select your data in Excel, then click above: a column of dates or labels and a
            column of values, with headers in the first row.
          </span>
          <Button appearance="subtle" size="small" onClick={handleSampleData}
            disabled={isLoadingSample} style={{ borderRadius: '6px' }}>
            {isLoadingSample ? 'Adding sample…' : 'Try with sample data'}
          </Button>
        </div>
      ) : (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Data Source</div>
          <div className={styles.dataSourceBar}>
            <span className={styles.address}>{rangeAddress}</span>
            <Button size="small" icon={<ArrowSyncRegular />} appearance="subtle"
              onClick={handleSelectData} title="Re-read selection" aria-label="Re-read selection"
              style={{ borderRadius: '6px' }} />
          </div>
          {hasData && (
            <button className={styles.settingsToggle} onClick={() => setPreviewOpen(o => !o)}
              aria-expanded={previewOpen} aria-controls="spc-data-preview"
              style={{ marginTop: '8px' }}>
              {previewOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
              Data preview
            </button>
          )}
          {previewOpen && hasData && (
            <div style={{ marginTop: '8px' }} id="spc-data-preview">
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
          <button className={styles.settingsToggle} onClick={() => setSettingsOpen(o => !o)}
            aria-expanded={settingsOpen} aria-controls="spc-settings-panel">
            <SettingsRegular style={{ fontSize: '14px' }} />
            Settings
            {settingsOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
          </button>

          {settingsOpen && (
            <div className={styles.settingsPanel} id="spc-settings-panel">
              <SignalMethodPicker value={options.method} onChange={method => patchOptions({ method })} />
              <LimitOptions options={options} needsSubgroup={needsSubgroup} onChange={patchOptions} />
            </div>
          )}
        </div>
      )}

      {/* ── Error ── */}
      <ErrorNotice error={error} panel="SPC" className={styles.error} />

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

          {findings && <FindingsPanel findings={findings} skipped={skipped} />}

          <AnnotationList annotations={annotations} onRemove={handleRemoveAnnotation} />

          <SummaryPanel result={result} />

          {/* Write actions */}
          <div className={styles.actions}>
            <Checkbox label="Include source data" checked={includeDataTable}
              onChange={(_, d) => setIncludeDataTable(!!d.checked)} />
            <Button appearance="primary" disabled={isWriting}
              icon={isWriting ? <Spinner size="tiny" /> : <ArrowDownloadRegular />}
              onClick={handleWriteToSheet} style={{ borderRadius: '6px' }}>
              {isWriting ? 'Writing…' : 'Write to Sheet'}
            </Button>
          </div>
          <LiveUpdateStatus {...liveUpdate} />
        </>
      ) : hasData && !error ? (
        <div className={styles.emptyChart}>Computing chart…</div>
      ) : null}
    </div>
  );
};
