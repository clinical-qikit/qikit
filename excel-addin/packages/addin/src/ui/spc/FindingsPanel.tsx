import React, { useState } from 'react';
import { ChevronDownRegular, ChevronRightRegular } from '@fluentui/react-icons';
import { Findings } from './findings';
import { SkippedRow } from './data-prep';
import { qikit } from '../../theme/tokens';

interface FindingsPanelProps {
  findings: Findings;
  skipped: SkippedRow[];
}

const SHOW_SKIPPED = 8;

/** What the chart shows, in sentences, with what limits it and the rows left out. Always visible. */
export const FindingsPanel: React.FC<FindingsPanelProps> = ({ findings, skipped }) => {
  const [skippedOpen, setSkippedOpen] = useState(false);
  const { verdict, signal, details, notes } = findings;

  return (
    <div style={{ padding: '0 16px', marginTop: '10px' }}>
      <div role="status" aria-live="polite" style={{
        padding: '10px 12px', borderRadius: qikit.radius.md,
        border: `1px solid ${signal ? qikit.color.dangerBorder : qikit.color.brandTintBorder}`,
        backgroundColor: signal ? qikit.color.dangerBg : qikit.color.brandTint,
        fontSize: '12.5px', lineHeight: 1.45, color: qikit.color.ink,
      }}>
        <div style={{ fontWeight: 600, color: signal ? qikit.color.danger : qikit.color.brand }}>{verdict}</div>
        {details.map((d, i) => <div key={i} style={{ marginTop: '4px' }}>{d}</div>)}
      </div>

      {notes.map((n, i) => (
        <div key={i} style={{
          marginTop: '8px', padding: '8px 10px', borderRadius: qikit.radius.md,
          border: `1px solid ${qikit.color.noteBorder}`, backgroundColor: qikit.color.noteBg,
          color: qikit.color.note, fontSize: '12px', lineHeight: 1.45,
        }}>{n}</div>
      ))}

      {skipped.length > 0 && (
        <div style={{ marginTop: '8px', fontSize: '12px', color: qikit.color.text }}>
          <button onClick={() => setSkippedOpen(o => !o)} aria-expanded={skippedOpen}
            aria-controls="spc-skipped-rows"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '4px', border: 'none',
              background: 'none', padding: 0, cursor: 'pointer', fontFamily: 'inherit',
              fontSize: '12px', color: qikit.color.note,
            }}>
            {skippedOpen ? <ChevronDownRegular /> : <ChevronRightRegular />}
            {skipped.length} row{skipped.length === 1 ? '' : 's'} left out of the chart
          </button>
          {skippedOpen && (
            <ul id="spc-skipped-rows" style={{ margin: '6px 0 0', paddingLeft: '18px' }}>
              {skipped.slice(0, SHOW_SKIPPED).map(s => (
                <li key={s.row}>Row {s.row}: {s.reason}</li>
              ))}
              {skipped.length > SHOW_SKIPPED && <li>and {skipped.length - SHOW_SKIPPED} more</li>}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
