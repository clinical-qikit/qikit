import React from 'react';
import { 
  Table, TableHeader, TableRow, TableHeaderCell, TableBody, TableCell, 
  Text, makeStyles, tokens, Badge
} from '@fluentui/react-components';

const useStyles = makeStyles({
  container: {
    marginTop: '12px',
    border: `1px solid ${tokens.colorNeutralStroke1}`,
    borderRadius: tokens.borderRadiusMedium,
    overflow: 'hidden',
  },
  title: {
    padding: '8px 12px',
    backgroundColor: tokens.colorNeutralBackground3,
    borderBottom: `1px solid ${tokens.colorNeutralStroke1}`,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  table: {
    maxHeight: '200px',
    overflowY: 'auto',
  },
  empty: {
    padding: '20px',
    textAlign: 'center',
    color: tokens.colorNeutralForeground3,
  }
});

interface DataPreviewProps {
  data: (string | number | null)[][];
  hasHeaders?: boolean;
}

export const DataPreview: React.FC<DataPreviewProps> = ({ data, hasHeaders = false }) => {
  const styles = useStyles();

  if (!data || data.length === 0) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>
          <Text>No data selected</Text>
        </div>
      </div>
    );
  }

  const previewRows = data.slice(0, 6); // Up to 6 rows (1 header + 5 data)
  const columns = previewRows[0]?.length || 0;

  return (
    <div className={styles.container}>
      <div className={styles.title}>
        <Text weight="semibold">Data Preview</Text>
        <Badge appearance="outline">{data.length} rows × {columns} cols</Badge>
      </div>
      <Table size="extra-small" className={styles.table}>
        <TableBody>
          {previewRows.map((row, i) => (
            <TableRow key={i}>
              {row.map((cell, j) => (
                <TableCell key={j}>
                  <Text size={100} truncate>{cell?.toString() ?? ''}</Text>
                </TableCell>
              ))}
            </TableRow>
          ))}
          {data.length > 6 && (
            <TableRow>
              <TableCell colSpan={columns}>
                <Text size={100} italic>... {data.length - 6} more rows</Text>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
};
