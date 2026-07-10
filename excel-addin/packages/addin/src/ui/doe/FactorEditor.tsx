import React from 'react';
import {
  Button, Input, makeStyles,
} from '@fluentui/react-components';
import { AddRegular, DismissRegular } from '@fluentui/react-icons';
import { qikit } from '../../theme/tokens';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  header: {
    display: 'grid',
    gridTemplateColumns: '1fr 64px 64px 32px',
    gap: '6px',
    paddingBottom: '4px',
  },
  headerCell: {
    fontSize: '11px',
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    color: qikit.color.textMuted,
  },
  row: {
    display: 'grid',
    gridTemplateColumns: '1fr 64px 64px 32px',
    gap: '6px',
    alignItems: 'center',
  },
  addBtn: {
    alignSelf: 'flex-start',
    marginTop: '4px',
  },
});

export interface Factor {
  name: string;
  low: string;
  high: string;
}

interface FactorEditorProps {
  factors: Factor[];
  onChange: (factors: Factor[]) => void;
}

export const FactorEditor: React.FC<FactorEditorProps> = ({ factors, onChange }) => {
  const styles = useStyles();

  const addFactor = () => {
    const nextLetter = String.fromCharCode(65 + factors.length);
    onChange([...factors, { name: nextLetter, low: '-1', high: '1' }]);
  };

  const removeFactor = (index: number) => {
    onChange(factors.filter((_, i) => i !== index));
  };

  const updateFactor = (index: number, field: keyof Factor, value: string) => {
    const newFactors = [...factors];
    newFactors[index][field] = value;
    onChange(newFactors);
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.headerCell}>Factor</span>
        <span className={styles.headerCell}>Low</span>
        <span className={styles.headerCell}>High</span>
        <span />
      </div>
      {factors.map((f, i) => (
        <div key={i} className={styles.row}>
          <Input
            size="small"
            value={f.name}
            onChange={(_, d) => updateFactor(i, 'name', d.value)}
          />
          <Input
            size="small"
            value={f.low}
            onChange={(_, d) => updateFactor(i, 'low', d.value)}
          />
          <Input
            size="small"
            value={f.high}
            onChange={(_, d) => updateFactor(i, 'high', d.value)}
          />
          <Button
            icon={<DismissRegular />}
            appearance="transparent"
            size="small"
            onClick={() => removeFactor(i)}
            disabled={factors.length <= 2}
            style={{ minWidth: '28px', padding: 0 }}
          />
        </div>
      ))}
      <div className={styles.addBtn}>
        <Button
          icon={<AddRegular />}
          size="small"
          appearance="subtle"
          onClick={addFactor}
          style={{ borderRadius: '6px' }}
        >
          Add Factor
        </Button>
      </div>
    </div>
  );
};
