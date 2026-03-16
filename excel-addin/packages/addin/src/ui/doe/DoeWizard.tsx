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

import { DesignConfigurator } from './DesignConfigurator';

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
    marginBottom: '8px',
  },
  errorText: {
    color: tokens.colorPaletteRedForeground1,
    marginTop: '8px',
    padding: '8px',
    backgroundColor: tokens.colorPaletteRedBackground1,
    borderRadius: '4px'
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
  const [designType, setDesignType] = useState<'full_factorial' | 'fractional'>('full_factorial');
  const [currentDesign, setCurrentDesign] = useState<DOEDesign | null>(null);
  const [result, setResult] = useState<DOEResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onGenerate = () => {
    setError(null);
    try {
      if (factors.length < 2) {
        throw new Error("At least 2 factors are required.");
      }
      if (factors.some(f => !f.name.trim() || isNaN(parseFloat(f.low)) || isNaN(parseFloat(f.high)))) {
        throw new Error("All factors must have valid names and numeric levels.");
      }

      const d = design({
        factors: factors.map(f => f.name),
        lows: factors.map(f => parseFloat(f.low)),
        highs: factors.map(f => parseFloat(f.high)),
        design_type: designType
      });
      setCurrentDesign(d);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate design.");
      console.error(err);
    }
  };

  const onExampleLoaded = (data: any[][]) => {
    // Example: ['RunOrder', 'A', 'B', 'Response']
    const headers = data[0];
    const factorNames = headers.filter((h: string) => h !== 'RunOrder' && h !== 'Response');
    setFactors(factorNames.map((name: string) => ({
      name,
      low: '-1',
      high: '1'
    })));
  };

  const onWriteTemplate = async () => {
    setError(null);
    if (!currentDesign) return;
    try {
      const headers = ['RunOrder', ...currentDesign.factors, 'Response'];
      const rows = currentDesign.matrix.map(row => headers.map(h => row[h]));
      await writeToNewSheet(`DOE ${currentDesign.n_factors}F`, [headers, ...rows]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to write template to sheet.");
      console.error(err);
    }
  };

  const onReadResults = async () => {
    setError(null);
    try {
      const resData = await getSelectedRangeValues();
      const headers = resData.values[0];
      const respIdx = headers.indexOf('Response');
      if (respIdx === -1) throw new Error("No 'Response' column found. Ensure you include the headers in your selection.");
      
      const response = resData.values.slice(1).map(row => row[respIdx]).filter(v => typeof v === 'number') as number[];
      
      if (currentDesign) {
        if (response.length !== currentDesign.n_runs) {
           throw new Error(`Expected ${currentDesign.n_runs} responses, but found ${response.length}.`);
        }
        const res = analyze(currentDesign, response);
        setResult(res);
        setStep(3);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to read or analyze results.");
      console.error(err);
    }
  };

  const onWriteResults = async () => {
    if (!result) return;
    try {
      const sheetData = [
        ['Term', 'Effect', 'Coefficient'],
        ...result.effects.map(e => [e.name, e.effect, e.coefficient])
      ];
      const { sheetName, rangeAddress } = await writeToNewSheet(`DOE Effects`, sheetData);
      const { createEffectsChart } = await import('../../excel/chart-builder');
      await createEffectsChart(result, sheetName, rangeAddress);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to write DOE results to sheet.");
      console.error(err);
    }
  };

  const onReset = () => {
    setStep(1);
    setFactors([
      { name: 'A', low: '-1', high: '1' },
      { name: 'B', low: '-1', high: '1' }
    ]);
    setDesignType('full_factorial');
    setCurrentDesign(null);
    setResult(null);
    setError(null);
  };

  return (
    <div className={styles.container}>
      <StepIndicator currentStep={step} steps={STEPS} />
      
      {error && (
        <div className={styles.errorText}>
          <Text>{error}</Text>
        </div>
      )}

      {step === 1 && (
        <div className={styles.stepContainer}>
          <ExampleLoader type="doe" onLoaded={onExampleLoaded} />
          <Text weight="semibold">Step 1: Define Factors</Text>
          <FactorEditor factors={factors} onChange={setFactors} />
          <DesignConfigurator 
            nFactors={factors.length} 
            designType={designType} 
            onDesignTypeChange={setDesignType} 
          />
          <div className={styles.actions}>
            <Button appearance="primary" onClick={onGenerate}>Choose Design</Button>
          </div>
        </div>
      )}

      {step === 2 && currentDesign && (
        <div className={styles.stepContainer}>
          <Text weight="semibold">Step 2: Generate & Run</Text>
          <Card className={styles.designBadge}>
            <Text>Design: <strong>{currentDesign.design_type}</strong></Text>
            <Badge appearance="tint" color="informative">{currentDesign.n_runs} runs</Badge>
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
            <Button appearance="primary" onClick={onWriteResults}>Write to Sheet</Button>
            <Button appearance="secondary" onClick={onReset}>Start New</Button>
          </div>
        </div>
      )}
    </div>
  );
};
