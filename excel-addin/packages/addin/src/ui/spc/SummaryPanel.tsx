import React, { useState } from 'react';
import { ChevronDownRegular, ChevronRightRegular } from '@fluentui/react-icons';
import { SPCResult } from '@qikit/engine';
import { useSpcStyles } from './styles';

interface SummaryPanelProps {
  result: SPCResult;
}

/** Collapsible analysis summary: signal badge, run/crossing counts, triggered rules, limits. */
export const SummaryPanel: React.FC<SummaryPanelProps> = ({ result }) => {
  const styles = useSpcStyles();
  const [summaryOpen, setSummaryOpen] = useState(false);

  return (
    <div style={{ padding: '0 16px', marginTop: '8px' }}>
      <button className={styles.settingsToggle} onClick={() => setSummaryOpen(o => !o)}>
        {summaryOpen ? <ChevronDownRegular style={{ fontSize: '12px' }} /> : <ChevronRightRegular style={{ fontSize: '12px' }} />}
        Analysis summary
      </button>
      {summaryOpen && (
        <div style={{ marginTop: '8px', padding: '10px', backgroundColor: '#f6f6f8', borderRadius: '6px', border: '1px solid #e8e6e3' }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', padding: '4px 10px', borderRadius: '4px',
            fontSize: '12px', fontWeight: '600', marginBottom: '10px',
            backgroundColor: result.signals ? '#fdf2f2' : '#e8f5f2',
            color: result.signals ? '#c4314b' : '#107C6C',
          }}>
            {result.signals ? '⚠️ Signal detected' : '✓ No signal'}
          </div>
          <div className={styles.summaryTable}>
            <div className={styles.summaryItem}>
              <div className={styles.summaryKey}>Observations</div>
              <div className={styles.summaryVal}>{result.summary.n_obs ?? '—'}</div>
            </div>
            <div className={styles.summaryItem}>
              <div className={styles.summaryKey}>Method</div>
              <div className={styles.summaryVal}>{result.method}</div>
            </div>
            {result.summary.longest_run !== undefined && (
              <>
                <div className={styles.summaryItem}>
                  <div className={styles.summaryKey}>Longest run</div>
                  <div className={styles.summaryVal}>{result.summary.longest_run} (lim {result.summary.run_threshold})</div>
                </div>
                <div className={styles.summaryItem}>
                  <div className={styles.summaryKey}>Crossings</div>
                  <div className={styles.summaryVal}>{result.summary.n_crossings} (lim {result.summary.crossings_threshold})</div>
                </div>
              </>
            )}
            {result.summary.weco_rules_triggered && (
              <div className={styles.summaryItem} style={{ gridColumn: '1 / -1' }}>
                <div className={styles.summaryKey}>WECO rules triggered</div>
                <div className={styles.summaryVal}>
                  {result.summary.weco_rules_triggered.length > 0 ? result.summary.weco_rules_triggered.join(', ') : 'None'}
                </div>
              </div>
            )}
            {result.summary.nelson_rules_triggered && (
              <div className={styles.summaryItem} style={{ gridColumn: '1 / -1' }}>
                <div className={styles.summaryKey}>Nelson rules triggered</div>
                <div className={styles.summaryVal}>
                  {result.summary.nelson_rules_triggered.length > 0 ? result.summary.nelson_rules_triggered.join(', ') : 'None'}
                </div>
              </div>
            )}
            {result.data[0] && !isNaN(result.data[0].cl) && (
              <>
                <div className={styles.summaryItem}>
                  <div className={styles.summaryKey}>CL</div>
                  <div className={styles.summaryVal}>{result.data[0].cl.toFixed(3)}</div>
                </div>
                <div className={styles.summaryItem}>
                  <div className={styles.summaryKey}>UCL</div>
                  <div className={styles.summaryVal}>{isNaN(result.data[0].ucl) ? '—' : result.data[0].ucl.toFixed(3)}</div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
