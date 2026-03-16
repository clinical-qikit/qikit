import React from 'react';
import { makeStyles, tokens, Text } from '@fluentui/react-components';
import { CheckmarkCircle16Filled, Circle16Regular } from '@fluentui/react-icons';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '8px 0',
    marginBottom: '16px',
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  step: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  active: {
    color: tokens.colorBrandForeground1,
    fontWeight: tokens.fontWeightSemibold,
  },
  inactive: {
    color: tokens.colorNeutralForeground3,
  }
});

interface StepIndicatorProps {
  currentStep: number;
  steps: string[];
}

export const StepIndicator: React.FC<StepIndicatorProps> = ({ currentStep, steps }) => {
  const styles = useStyles();

  return (
    <div className={styles.container}>
      {steps.map((step, i) => {
        const isCompleted = i + 1 < currentStep;
        const isActive = i + 1 === currentStep;
        
        return (
          <div key={i} className={`${styles.step} ${isActive ? styles.active : styles.inactive}`}>
            {isCompleted ? <CheckmarkCircle16Filled /> : <Circle16Regular />}
            <Text size={100}>{step}</Text>
          </div>
        );
      })}
    </div>
  );
};
