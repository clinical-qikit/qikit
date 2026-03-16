import React, { useState } from 'react';
import { 
  Button, makeStyles, tokens, Text, 
  Title3, Badge, Card, Field
} from '@fluentui/react-components';
import { design, analyze, DOEDesign, DOEResult } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import { FactorEditor, Factor } from './FactorEditor';
import { ChartViewer } from '../shared/ChartViewer';
import { InterpretationPanel } from '../shared/InterpretationPanel';
import { StepIndicator } from '../shared/StepIndicator';
import { ExampleLoader } from '../shared/ExampleLoader';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
    padding: '16px',
  },
  stepContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  actions: {
    display: 'flex',
    gap: '8px',
    marginTop: '12px',
  },
  designBadge: {
    padding: '8px',
    backgroundColor: tokens.colorNeutralBackground2,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  }
});

const STEPS = ['Define Factors', 'Run Experiment', 'Results'];

export const DoeWizard: React.FC = () => {
  const styles = useStyles();
  const [step, setStep] = useState(1);
  const [factors, setFactors] = useState<Factor[]>([
    { name: 'A', low: '-1', high: '1' },
    { name: 'B', low: '-1', high: '1' }
  ]);
  const [currentDesign, setCurrentDesign] = useState<DOEDesign | null>(null);
  const [result, setResult] = useState<DOEResult | null>(null);

  const onGenerate = () => {
    try {
      const d = design({
        factors: factors.map(f => f.name),
        lows: factors.map(f => parseFloat(f.low)),
        highs: factors.map(f => parseFloat(f.high)),
        design_type: factors.length > 3 ? 'fractional' : 'full_factorial'
      });
      setCurrentDesign(d);
      setStep(2);
    } catch (err) {
      console.error(err);
    }
  };

  const onWriteTemplate = async () => {
    if (!currentDesign) return;
    const headers = ['RunOrder', ...currentDesign.factors, 'Response'];
    const rows = currentDesign.matrix.map(row => headers.map(h => row[h]));
    await writeToNewSheet(`DOE ${currentDesign.n_factors}F`, [headers, ...rows]);
  };

  const onReadResults = async () => {
    try {
      const resData = await getSelectedRangeValues();
      const headers = resData.values[0];
      const respIdx = headers.indexOf('Response');
      if (respIdx === -1) throw new Error("No 'Response' column found");
      
      const response = resData.values.slice(1).map(row => row[respIdx]).filter(v => typeof v === 'number') as number[];
      
      if (currentDesign) {
        const res = analyze(currentDesign, response);
        setResult(res);
        setStep(3);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const onReset = () => {
    setStep(1);
    setFactors([
      { name: 'A', low: '-1', high: '1' },
      { name: 'B', low: '-1', high: '1' }
    ]);
    setCurrentDesign(null);
    setResult(null);
  };

  return (
    <div className={styles.container}>
      <StepIndicator currentStep={step} steps={STEPS} />
      
      {step === 1 && (
        <div className={styles.stepContainer}>
          <ExampleLoader type="doe" onLoaded={() => {}} />
          <Text weight="semibold">Step 1: Define Factors</Text>
          <FactorEditor factors={factors} onChange={setFactors} />
          <Button appearance="primary" onClick={onGenerate}>Choose Design</Button>
        </div>
      )}

      {step === 2 && currentDesign && (
        <div className={styles.stepContainer}>
          <Text weight="semibold">Step 2: Generate & Run</Text>
          <Card className={styles.designBadge}>
            <Text>Design: <strong>{currentDesign.design_type}</strong></Text>
            <Badge>{currentDesign.n_runs} runs</Badge>
          </Card>
          <Text size={200}>Generate a template sheet, run your experiment, and enter results in the Response column.</Text>
          <div className={styles.actions}>
            <Button onClick={onWriteTemplate}>Write Template</Button>
            <Button appearance="primary" onClick={onReadResults}>Read Results</Button>
          </div>
          <Button appearance="subtle" onClick={() => setStep(1)}>Back</Button>
        </div>
      )}

      {step === 3 && result && (
        <div className={styles.stepContainer}>
          <Text weight="semibold">Step 3: Results</Text>
          <ChartViewer result={result} type="doe" />
          <InterpretationPanel result={result} type="doe" />
          <div className={styles.actions}>
            <Button appearance="secondary" onClick={onReset}>Start New</Button>
          </div>
        </div>
      )}
    </div>
  );
};
