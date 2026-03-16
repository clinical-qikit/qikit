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
  }
});

const STEPS = ['Select Data', 'Describe', 'Results'];

export const SpcWizard: React.FC = () => {
  const styles = useStyles();
  const [step, setStep] = useState(1);
  const [data, setData] = useState<any[][]>([]);
  const [chartType, setChartType] = useState<ChartType | null>(null);
  const [result, setResult] = useState<SPCResult | null>(null);

  const onSelectData = async () => {
    try {
      const res = await getSelectedRangeValues();
      setData(res.values);
    } catch (err) {
      console.error(err);
    }
  };

  const onChartResolved = (type: ChartType) => {
    setChartType(type);
    
    // Auto-compute
    try {
      // Very basic extraction: assume first col is data if only 1 col, 
      // or second col is data if multiple.
      const rawY = data.map(row => row[data[0].length > 1 ? 1 : 0]);
      const numericY = rawY.filter(v => typeof v === 'number') as number[];
      
      const res = compute({
        y: numericY,
        chart: type
      });
      setResult(res);
      setStep(3);
    } catch (err) {
      console.error(err);
    }
  };

  const onReset = () => {
    setStep(1);
    setData([]);
    setChartType(null);
    setResult(null);
  };

  const onWriteToSheet = async () => {
    if (!result) return;
    const sheetData = [
      ['Point', 'Value', 'CL', 'UCL', 'LCL', 'Signal'],
      ...result.data.map((d, i) => [
        i + 1, d.y, d.cl, d.ucl, d.lcl, d.sigma_signal || d.runs_signal
      ])
    ];
    await writeToNewSheet(`SPC ${result.chart_type.toUpperCase()}`, sheetData);
  };

  return (
    <div className={styles.container}>
      <StepIndicator currentStep={step} steps={STEPS} />
      
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
