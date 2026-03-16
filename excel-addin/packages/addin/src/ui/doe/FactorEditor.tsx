import React, { useState } from 'react';
import { 
  Button, Input, makeStyles, tokens, Text, 
  Field, Title3, Table, TableHeader, TableRow, TableHeaderCell, TableBody, TableCell
} from '@fluentui/react-components';
import { Add16Regular, Delete16Regular } from '@fluentui/react-icons';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  row: {
    display: 'flex',
    gap: '8px',
    alignItems: 'flex-end',
  }
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
      <Text weight="semibold">Factor Definition</Text>
      <Table size="extra-small">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>Name</TableHeaderCell>
            <TableHeaderCell>Low</TableHeaderCell>
            <TableHeaderCell>High</TableHeaderCell>
            <TableHeaderCell />
          </TableRow>
        </TableHeader>
        <TableBody>
          {factors.map((f, i) => (
            <TableRow key={i}>
              <TableCell>
                <Input 
                  size="small" 
                  value={f.name} 
                  onChange={(_, d) => updateFactor(i, 'name', d.value)} 
                  style={{ width: '60px' }}
                />
              </TableCell>
              <TableCell>
                <Input 
                  size="small" 
                  value={f.low} 
                  onChange={(_, d) => updateFactor(i, 'low', d.value)} 
                  style={{ width: '60px' }}
                />
              </TableCell>
              <TableCell>
                <Input 
                  size="small" 
                  value={f.high} 
                  onChange={(_, d) => updateFactor(i, 'high', d.value)} 
                  style={{ width: '60px' }}
                />
              </TableCell>
              <TableCell>
                <Button 
                  icon={<Delete16Regular />} 
                  appearance="transparent" 
                  size="small"
                  onClick={() => removeFactor(i)}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Button icon={<Add16Regular />} size="small" onClick={addFactor}>Add Factor</Button>
    </div>
  );
};
