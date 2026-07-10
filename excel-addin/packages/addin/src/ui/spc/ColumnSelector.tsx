import React from 'react';
import { Select } from '@fluentui/react-components';
import { ChartType } from '@qikit/engine';
import { useSpcStyles } from './styles';
import { NEEDS_N, GRAIN_CHARTS, DataGrain } from './constants';
import { DateAggregationOptions } from './DateAggregationOptions';
import { qikit } from '../../theme/tokens';

interface ColumnSelectorProps {
  headers: string[];
  numericCols: number[];
  chartType: ChartType;
  dataGrain: DataGrain;
  xCol: number | null;
  yCol: number;
  nCol: number | null;
  notesCol: number | null;
  isDateX: boolean;
  xPeriod: string;
  onDataGrainChange: (grain: DataGrain) => void;
  onXColChange: (col: number | null) => void;
  onYColChange: (col: number) => void;
  onNColChange: (col: number | null) => void;
  onNotesColChange: (col: number | null) => void;
  onXPeriodChange: (period: string) => void;
}

export const ColumnSelector: React.FC<ColumnSelectorProps> = ({
  headers, numericCols, chartType, dataGrain,
  xCol, yCol, nCol, notesCol, isDateX, xPeriod,
  onDataGrainChange, onXColChange, onYColChange, onNColChange, onNotesColChange, onXPeriodChange,
}) => {
  const styles = useSpcStyles();

  const needsN = NEEDS_N.includes(chartType);
  const supportsGrain = GRAIN_CHARTS.includes(chartType);
  const isIndividual = supportsGrain && dataGrain === 'individual';
  const allCols = headers.map((_, i) => i);

  const nLabel = ['u', 'up'].includes(chartType) ? 'Exposure' : 'Sample size';
  const nTooltip = ['u', 'up'].includes(chartType)
    ? 'Exposure units per period (e.g. catheter-days, patient-days). The chart divides your count by this to get a rate.'
    : 'Sample size per period (e.g. number of discharges). The chart divides your count by this to get a proportion.';
  const yTooltip = isIndividual
    ? (['p', 'pp', 'ip'].includes(chartType)
        ? 'Binary outcome: 1 if the event occurred, 0 if not. Do not pre-aggregate — the chart sums these per period.'
        : ['u', 'up'].includes(chartType)
          ? 'Defect or event count for this unit (often 0 or 1). The chart will sum per period and divide by unit count.'
          : 'Event count per row. Rows will be summed per period.')
    : undefined;

  return (
    <div className={styles.section}>
      <div className={styles.sectionLabel}>Columns</div>

      {/* Data grain (attribute + count charts) */}
      {supportsGrain && (
        <div className={styles.colRow}>
          <span className={styles.colLabel} style={{ minWidth: '62px' }}>Each row is</span>
          <Select size="small" value={dataGrain}
            onChange={(_, d) => onDataGrainChange(d.value as DataGrain)}
            style={{ flex: 1 }}>
            <option value="summarized">Period summary</option>
            <option value="individual">Individual record</option>
          </Select>
        </div>
      )}

      {/* X */}
      <div className={styles.colRow}>
        <span className={styles.colLabel} style={{ minWidth: supportsGrain ? '62px' : undefined }}>X</span>
        <Select size="small" value={xCol !== null ? String(xCol) : ''}
          onChange={(_, d) => onXColChange(d.value !== '' ? parseInt(d.value) : null)}
          style={{ flex: 1 }}>
          <option value="">— index</option>
          {allCols.map(ci => (
            <option key={ci} value={ci}>{headers[ci]}</option>
          ))}
        </Select>
      </div>

      {/* Y */}
      <div className={styles.colRow}>
        <span className={styles.colLabel} style={{ minWidth: supportsGrain ? '62px' : undefined }} title={yTooltip}>Y</span>
        <Select size="small" value={String(yCol)}
          onChange={(_, d) => onYColChange(parseInt(d.value))} style={{ flex: 1 }}>
          {numericCols.map(ci => (
            <option key={ci} value={ci}>{headers[ci]}</option>
          ))}
        </Select>
      </div>

      {/* N (attribute charts, summarized mode only) */}
      {needsN && !isIndividual && (
        <div className={styles.colRow}>
          <span className={styles.colLabel} style={{ minWidth: '62px' }} title={nTooltip}>{nLabel}</span>
          <Select size="small" value={nCol !== null ? String(nCol) : ''}
            onChange={(_, d) => onNColChange(d.value !== '' ? parseInt(d.value) : null)}
            style={{ flex: 1 }}>
            <option value="">— none</option>
            {numericCols.map(ci => (
              <option key={ci} value={ci}>{headers[ci]}</option>
            ))}
          </Select>
        </div>
      )}

      {/* Date Subgroup (only when X is a date column) */}
      {isDateX && <DateAggregationOptions xPeriod={xPeriod} onChange={onXPeriodChange} />}

      {/* Notes column */}
      <div className={styles.colRow} style={{ marginTop: '2px' }}>
        <span className={styles.colLabel} style={{ fontSize: '11px', color: qikit.color.textMuted, minWidth: supportsGrain ? '62px' : undefined }}>Notes</span>
        <Select size="small" value={notesCol !== null ? String(notesCol) : ''}
          onChange={(_, d) => onNotesColChange(d.value !== '' ? parseInt(d.value) : null)}
          style={{ flex: 1 }}>
          <option value="">— none</option>
          {allCols.map(ci => (
            <option key={ci} value={ci}>{headers[ci]}</option>
          ))}
        </Select>
      </div>
    </div>
  );
};
