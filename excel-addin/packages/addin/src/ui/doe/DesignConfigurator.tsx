import React from 'react';
import { 
  RadioGroup, Radio, Text, makeStyles, tokens, Badge, Card
} from '@fluentui/react-components';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    marginTop: '16px',
    padding: '12px',
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusMedium,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  }
});

interface DesignConfiguratorProps {
  nFactors: number;
  designType: 'full_factorial' | 'fractional';
  onDesignTypeChange: (type: 'full_factorial' | 'fractional') => void;
}

export const DesignConfigurator: React.FC<DesignConfiguratorProps> = ({ 
  nFactors, designType, onDesignTypeChange 
}) => {
  const styles = useStyles();

  const getRunCount = () => {
    if (designType === 'full_factorial') {
      return Math.pow(2, nFactors);
    } else {
      // Very simplistic: assume resolution IV (half-fraction) for fractional
      return Math.pow(2, nFactors - 1);
    }
  };

  const isFractionalPossible = nFactors >= 3;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Text weight="semibold">Configure Design</Text>
        <Badge appearance="tint" color="brand">Runs: {getRunCount()}</Badge>
      </div>

      <RadioGroup 
        value={designType} 
        onChange={(_, data) => onDesignTypeChange(data.value as any)}
      >
        <Radio value="full_factorial" label="Full Factorial (All combinations)" />
        <Radio 
          value="fractional" 
          label="Fractional Factorial (Fewer runs, lower resolution)" 
          disabled={!isFractionalPossible}
        />
      </RadioGroup>

      {!isFractionalPossible && designType === 'fractional' && (
        <Text size={200} style={{ color: tokens.colorPaletteRedForeground1 }}>
          Fractional design requires at least 3 factors.
        </Text>
      )}
    </div>
  );
};
