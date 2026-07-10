import React, { useState } from 'react';
import { Button, Input } from '@fluentui/react-components';
import { useSpcStyles } from './styles';
import { qikit } from '../../theme/tokens';

interface AnnotationBarProps {
  pointIdx: number;
  initialText: string;
  onSave: (idx: number, text: string) => void;
  onCancel: () => void;
}

/** Input bar for the annotation being edited. Remount (via key) when the point changes. */
export const AnnotationBar: React.FC<AnnotationBarProps> = ({ pointIdx, initialText, onSave, onCancel }) => {
  const styles = useSpcStyles();
  const [text, setText] = useState(initialText);

  return (
    <div className={styles.annotBar} style={{ marginTop: '8px' }}>
      <span className={styles.annotBarLabel}>Pt {pointIdx + 1}</span>
      <Input size="small" style={{ flex: 1 }} placeholder="Add a note…"
        value={text} onChange={(_, d) => setText(d.value)}
        onKeyDown={e => { if (e.key === 'Enter') onSave(pointIdx, text); if (e.key === 'Escape') onCancel(); }}
        autoFocus />
      <Button size="small" appearance="primary" onClick={() => onSave(pointIdx, text)} style={{ borderRadius: '6px' }}>Save</Button>
      <Button size="small" appearance="subtle" onClick={onCancel} style={{ borderRadius: '6px' }}>✕</Button>
    </div>
  );
};

interface AnnotationListProps {
  annotations: Record<number, string>;
  onRemove: (idx: number) => void;
}

export const AnnotationList: React.FC<AnnotationListProps> = ({ annotations, onRemove }) => {
  const styles = useSpcStyles();
  if (Object.keys(annotations).length === 0) return null;

  return (
    <div className={styles.annotList} style={{ marginTop: '8px' }}>
      {Object.entries(annotations).sort(([a], [b]) => parseInt(a) - parseInt(b)).map(([idx, text]) => (
        <div key={idx} className={styles.annotItem}>
          <span style={{ fontWeight: '600', color: qikit.color.note, fontSize: '11px' }}>{parseInt(idx) + 1}</span>
          <span className={styles.annotItemText}>{text}</span>
          <Button size="small" appearance="transparent" onClick={() => onRemove(parseInt(idx))}
            style={{ minWidth: '24px', padding: '2px' }}>✕</Button>
        </div>
      ))}
    </div>
  );
};
