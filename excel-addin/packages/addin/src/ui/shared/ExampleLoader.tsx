import React from 'react';
import { Button, makeStyles, tokens, Text } from '@fluentui/react-components';
import { Lightbulb16Regular } from '@fluentui/react-icons';
import { writeToNewSheet } from '../../excel/excel-io';

const useStyles = makeStyles({
  container: {
    padding: '8px 12px',
    backgroundColor: tokens.colorBrandBackground2,
    borderRadius: tokens.borderRadiusMedium,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '16px',
  }
});

interface ExampleLoaderProps {
  type: 'spc' | 'doe';
  onLoaded: (data: any[][]) => void;
}

const SPC_EXAMPLE = [
  ['Month', 'Defects', 'Total'],
  ['Jan', 12, 100], ['Feb', 15, 100], ['Mar', 8, 100], ['Apr', 10, 100],
  ['May', 4, 100], ['Jun', 7, 100], ['Jul', 16, 100], ['Aug', 9, 100],
  ['Sep', 14, 100], ['Oct', 10, 100], ['Nov', 5, 100], ['Dec', 6, 100],
  ['Jan', 17, 100], ['Feb', 12, 100], ['Mar', 22, 100], ['Apr', 8, 100]
];

const DOE_EXAMPLE = [
  ['RunOrder', 'A', 'B', 'Response'],
  [1, -1, -1, 10], [2, 1, -1, 20], [3, -1, 1, 15], [4, 1, 1, 25]
];

export const ExampleLoader: React.FC<ExampleLoaderProps> = ({ type, onLoaded }) => {
  const styles = useStyles();

  const loadExample = async () => {
    const data = type === 'spc' ? SPC_EXAMPLE : DOE_EXAMPLE;
    await writeToNewSheet(`Example ${type.toUpperCase()}`, data);
    onLoaded(data);
  };

  return (
    <div className={styles.container}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Lightbulb16Regular />
        <Text size={200}>New to this? Try an example.</Text>
      </div>
      <Button size="small" appearance="subtle" onClick={loadExample}>Load</Button>
    </div>
  );
};
