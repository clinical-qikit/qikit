import React, { useState } from 'react';
import { 
  Button, makeStyles, tokens, Text, 
  Divider, Title3 
} from '@fluentui/react-components';
import { ChartType, compute, SPCResult } from '@qikit/engine';
import { getSelectedRangeValues, writeToNewSheet } from '../../excel/excel-io';
import { DataPreview } from '../shared/DataPreview';
import { DataDescriber } from './DataDescriber';
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
  errorText: {
    color: tokens.colorPaletteRedForeground1,
    marginTop: '8px',
    padding: '8px',
    backgroundColor: tokens.colorPaletteRedBackground1,
    borderRadius: '4px'
  }
});

const STEPS = ['Select Data', 'Describe', 'Results'];

export const SpcWizard: React.FC = () => {
  const styles = useStyles();
  const [step, setStep] = useState(1);
  const [data, setData] = useState<any[][]>([]);
  const [chartType, setChartType] = useState<ChartType | null>(null);
  const [result, setResult] = useState<SPCResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSelectData = async () => {
    setError(null);
    try {
      const res = await getSelectedRangeValues();
      setData(res.values);
      if (res.values.length < 2) {
        setError("Please select at least 2 rows of data.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to select data.");
      console.error(err);
    }
  };

  const onChartResolved = (type: ChartType) => {
    setError(null);
    setChartType(type);
    
    // Auto-compute
    try {
      // Very basic extraction: assume first col is data if only 1 col, 
      // or second col is data if multiple.
      const rawY = data.map(row => row[data[0].length > 1 ? 1 : 0]);
      const numericY = rawY.filter(v => typeof v === 'number') as number[];
      
      if (numericY.length === 0) {
        throw new Error("No numeric data found in the selected range.");
      }
      
      const res = compute({
        y: numericY,
        chart: type
      });
      setResult(res);
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Computation failed.");
      console.error(err);
    }
  };

  const onReset = () => {
    setStep(1);
    setData([]);
    setChartType(null);
    setResult(null);
    setError(null);
  };

  const onWriteToSheet = async () => {
    if (!result) return;
    const sheetData = [
      ['Point', 'Value', 'CL', 'UCL', 'LCL', 'Signal'],
      ...result.data.map((d, i) => [
        i + 1, d.y, d.cl, d.ucl, d.lcl, d.sigma_signal || d.runs_signal ? 1 : null
      ])
    ];
    try {
      const { sheetName, rangeAddress } = await writeToNewSheet(`SPC ${result.chart_type.toUpperCase()}`, sheetData);
      const { createSPCChart } = await import('../../excel/chart-builder');
      await createSPCChart(result, sheetName, rangeAddress);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to write SPC results to sheet.");
      console.error(err);
    }
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
          <ExampleLoader type="spc" onLoaded={setData} />
          <Text weight="semibold">Step 1: Select Data</Text>
          <Text size={200}>Select a range in Excel containing your measurement data.</Text>
          <Button appearance="primary" onClick={onSelectData}>Use Current Selection</Button>
          {data.length > 0 && (
            <>
              <DataPreview data={data} />
              <Button appearance="secondary" onClick={() => setStep(2)}>Next</Button>
            </>
          )}
        </div>
      )}

      {step === 2 && (
        <div className={styles.stepContainer}>
          <Text weight="semibold">Step 2: Describe & Configure</Text>
          <DataDescriber onChartResolved={onChartResolved} />
          <Button appearance="subtle" onClick={() => setStep(1)}>Back</Button>
        </div>
      )}

      {step === 3 && result && (
        <div className={styles.stepContainer}>
          <Text weight="semibold">Step 3: Results</Text>
          <ChartViewer result={result} type="spc" />
          <InterpretationPanel result={result} type="spc" />
          <div className={styles.actions}>
            <Button appearance="primary" onClick={onWriteToSheet}>Write to Sheet</Button>
            <Button appearance="secondary" onClick={onReset}>Start New</Button>
          </div>
        </div>
      )}
    </div>
  );
};
