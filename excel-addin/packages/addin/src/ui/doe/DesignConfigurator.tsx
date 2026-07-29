import React from 'react';
import {
  RadioGroup, Radio, makeStyles, Badge, Input, Checkbox,
} from '@fluentui/react-components';
import { DesignType } from '@qikit/engine';
import { qikit } from '../../theme/tokens';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    padding: '14px',
    backgroundColor: qikit.color.surfaceAlt,
    borderRadius: qikit.radius.md,
    border: `1px solid ${qikit.color.borderSubtle}`,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  label: {
    fontSize: '12px',
    fontWeight: '600',
    color: qikit.color.ink,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '8px',
  },
  fieldLabel: {
    fontSize: '11px',
    color: qikit.color.text,
    marginBottom: '4px',
  },
  hint: {
    fontSize: '11px',
    color: qikit.color.danger,
    marginTop: '2px',
  },
  divider: {
    height: '1px',
    backgroundColor: qikit.color.border,
  },
});

interface DesignConfiguratorProps {
  nFactors: number;
  designType: DesignType;
  replicates: number;
  centerPoints: number;
  randomize: 'none' | 'full';
  seed: number;
  onDesignTypeChange: (type: DesignType) => void;
  onReplicatesChange: (n: number) => void;
  onCenterPointsChange: (n: number) => void;
  onRandomizeChange: (r: 'none' | 'full') => void;
  onSeedChange: (s: number) => void;
}

function computeRunCount(nFactors: number, designType: DesignType, replicates: number, centerPoints: number): number {
  let base: number;
  if (designType === 'full_factorial') base = Math.pow(2, nFactors);
  else if (designType === 'fractional') base = Math.pow(2, nFactors - 1);
  else base = nFactors + 1; // one_factor
  return base * replicates + centerPoints;
}

export const DesignConfigurator: React.FC<DesignConfiguratorProps> = ({
  nFactors, designType, replicates, centerPoints, randomize, seed,
  onDesignTypeChange, onReplicatesChange, onCenterPointsChange, onRandomizeChange, onSeedChange,
}) => {
  const styles = useStyles();
  const isFractionalPossible = nFactors >= 3;
  const runCount = computeRunCount(nFactors, designType, replicates, centerPoints);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.label}>Design Type</span>
        <Badge appearance="tint" color="brand" shape="rounded">
          {runCount} runs
        </Badge>
      </div>

      <RadioGroup
        value={designType}
        onChange={(_, data) => onDesignTypeChange(data.value as DesignType)}
      >
        <Radio value="full_factorial" label="Full Factorial" />
        <Radio
          value="fractional"
          label="Fractional Factorial"
          disabled={!isFractionalPossible}
        />
        <Radio value="one_factor" label="One Factor at a Time (OFAT)" />
      </RadioGroup>

      {!isFractionalPossible && designType === 'fractional' && (
        <span className={styles.hint}>Fractional design requires at least 3 factors.</span>
      )}

      <div className={styles.divider} />

      <div className={styles.grid}>
        <div>
          <div className={styles.fieldLabel}>Replicates</div>
          <Input
            size="small"
            type="number"
            value={String(replicates)}
            min="1"
            onChange={(_, d) => {
              const n = parseInt(d.value);
              if (!isNaN(n) && n >= 1) onReplicatesChange(n);
            }}
          />
        </div>
        <div>
          <div className={styles.fieldLabel}>Center Points</div>
          <Input
            size="small"
            type="number"
            value={String(centerPoints)}
            min="0"
            onChange={(_, d) => {
              const n = parseInt(d.value);
              if (!isNaN(n) && n >= 0) onCenterPointsChange(n);
            }}
          />
        </div>
      </div>

      <div>
        <Checkbox
          checked={randomize === 'full'}
          onChange={(_, d) => onRandomizeChange(d.checked ? 'full' : 'none')}
          label={<span style={{ fontSize: '12px' }}>Randomize run order</span>}
        />
      </div>

      {randomize === 'full' && (
        <div>
          <div className={styles.fieldLabel}>Random seed</div>
          <Input
            size="small"
            type="number"
            value={String(seed)}
            onChange={(_, d) => {
              const n = parseInt(d.value);
              if (!isNaN(n)) onSeedChange(n);
            }}
          />
        </div>
      )}
    </div>
  );
};
