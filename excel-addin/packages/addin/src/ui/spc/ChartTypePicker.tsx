import React, { useState } from 'react';
import { ChartType } from '@qikit/engine';
import { useSpcStyles } from './styles';
import { CORE_CHARTS, ADDITIONAL_CHARTS, CHART_LABELS } from './constants';
import { qikit } from '../../theme/tokens';

interface ChartTypePickerProps {
  chartType: ChartType;
  onChange: (chartType: ChartType) => void;
}

export const ChartTypePicker: React.FC<ChartTypePickerProps> = ({ chartType, onChange }) => {
  const styles = useSpcStyles();
  const [moreChartsOpen, setMoreChartsOpen] = useState(false);

  const pick = (ct: ChartType) => { onChange(ct); setMoreChartsOpen(false); };

  return (
    <div className={styles.section}>
      <div className={styles.sectionLabel}>Chart Type</div>
      <div className={styles.chartTypeRow}>
        {CORE_CHARTS.map(ct => (
          <button
            key={ct}
            aria-pressed={chartType === ct}
            title={CHART_LABELS[ct]}
            aria-label={CHART_LABELS[ct]}
            className={`${styles.chartBtn} ${chartType === ct ? styles.chartBtnActive : ''}`}
            onClick={() => pick(ct)}
          >{ct}</button>
        ))}
        <button
          aria-expanded={moreChartsOpen}
          aria-controls="spc-more-charts"
          className={`${styles.chartBtnMore} ${ADDITIONAL_CHARTS.includes(chartType) ? styles.chartBtnActive : ''}`}
          onClick={() => setMoreChartsOpen(o => !o)}
        >{ADDITIONAL_CHARTS.includes(chartType) ? chartType : 'more…'}</button>
      </div>
      {moreChartsOpen && (
        <div className={styles.chartMorePanel} id="spc-more-charts">
          {ADDITIONAL_CHARTS.map(ct => (
            <button
              key={ct}
              aria-pressed={chartType === ct}
              title={CHART_LABELS[ct]}
              aria-label={CHART_LABELS[ct]}
              className={`${styles.chartBtn} ${chartType === ct ? styles.chartBtnActive : ''}`}
              onClick={() => pick(ct)}
            >{ct}</button>
          ))}
        </div>
      )}
      {CHART_LABELS[chartType] && (
        <div style={{ fontSize: '11.5px', color: qikit.color.textMuted, marginTop: '8px', fontStyle: 'italic' }}>
          {CHART_LABELS[chartType]}
        </div>
      )}
    </div>
  );
};
