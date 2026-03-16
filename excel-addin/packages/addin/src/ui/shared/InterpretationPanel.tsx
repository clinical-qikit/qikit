import React from 'react';
import { Card, Text, makeStyles, tokens } from '@fluentui/react-components';
import { Info24Regular, Warning24Regular } from '@fluentui/react-icons';
import { SPCResult } from '@qikit/engine';
import { DOEResult } from '@qikit/engine';

const useStyles = makeStyles({
  card: {
    marginTop: '12px',
    padding: '12px',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '8px',
    fontWeight: tokens.fontWeightSemibold,
  },
  content: {
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
  },
  signal: {
    color: tokens.colorPaletteRedForeground1,
  }
});

interface InterpretationPanelProps {
  result: SPCResult | DOEResult;
  type: 'spc' | 'doe';
}

export const InterpretationPanel: React.FC<InterpretationPanelProps> = ({ result, type }) => {
  const styles = useStyles();

  const renderSPCInterpretation = (res: SPCResult) => {
    const signalCount = res.signals ? res.data.filter(d => d.sigma_signal || d.runs_signal).length : 0;
    const hasSignals = signalCount > 0;

    return (
      <>
        <div className={styles.header}>
          {hasSignals ? <Warning24Regular className={styles.signal} /> : <Info24Regular />}
          <Text>{hasSignals ? 'Special-Cause Variation Detected' : 'Process is Stable'}</Text>
        </div>
        <div className={styles.content}>
          <Text>
            {hasSignals 
              ? `${signalCount} point(s) show signs of special-cause variation, meaning something outside the normal system is affecting the process. Investigate these points to understand what changed.`
              : 'No special-cause variation was detected. The process appears to be stable and predictable. Any variation seen is likely due to common causes inherent to the system.'}
          </Text>
        </div>
      </>
    );
  };

  const renderDOEInterpretation = (res: DOEResult) => {
    const topEffect = [...res.effects].sort((a, b) => b.abs_effect - a.abs_effect)[0];
    const rSqPct = (res.r_squared * 100).toFixed(1);

    return (
      <>
        <div className={styles.header}>
          <Info24Regular />
          <Text>Key Insights</Text>
        </div>
        <div className={styles.content}>
          {topEffect ? (
            <Text>
              The factor <strong>{topEffect.term}</strong> has the largest impact on your results, changing the outcome by an average of {topEffect.effect.toFixed(2)} when moving from its low to high setting. 
              Overall, the factors in this model explain {rSqPct}% of the variation in the data.
            </Text>
          ) : (
            <Text>No significant factors were identified in this experiment.</Text>
          )}
        </div>
      </>
    );
  };

  return (
    <Card className={styles.card}>
      {type === 'spc' 
        ? renderSPCInterpretation(result as SPCResult) 
        : renderDOEInterpretation(result as DOEResult)}
    </Card>
  );
};
