import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { FluentProvider, webLightTheme, makeStyles, tokens, Button } from '@fluentui/react-components';

// --- Mocks ---

// Simple in-memory grid mock
const MOCK_DATA = [
  ['Month', 'Defects', 'Total'],
  ['Jan', 12, 100],
  ['Feb', 15, 100],
  ['Mar', 8, 100],
  ['Apr', 10, 100],
  ['May', 4, 100],
  ['Jun', 7, 100],
  ['Jul', 16, 100],
  ['Aug', 9, 100],
  ['Sep', 14, 100],
  ['Oct', 10, 100],
];

// @ts-ignore
window.Excel = {
  run: async (callback: (context: any) => Promise<any>) => {
    const context = {
      workbook: {
        getSelectedRange: () => ({
          load: () => {},
          values: MOCK_DATA,
          address: 'A1:C11'
        }),
        worksheets: {
          add: (name: string) => ({
            getRange: () => ({
              values: []
            }),
            activate: () => {}
          })
        }
      },
      sync: async () => {}
    };
    return callback(context);
  }
};

// @ts-ignore
window.Office = {
  onReady: (callback: (info: any) => void) => {
    callback({ host: 'Excel', platform: 'PC' });
  },
  context: {
    document: {
      settings: {
        get: () => null,
        set: () => {},
        saveAsync: (cb: any) => cb()
      }
    }
  }
};

// --- Harness Wrapper ---

const useStyles = makeStyles({
  harness: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
  },
  toolbar: {
    padding: '8px',
    backgroundColor: tokens.colorNeutralBackground3,
    borderBottom: `1px solid ${tokens.colorNeutralStroke1}`,
    display: 'flex',
    gap: '8px',
  },
  content: {
    flex: 1,
    overflow: 'auto',
    backgroundColor: tokens.colorNeutralBackground2,
    display: 'flex',
    justifyContent: 'center',
  },
  taskPaneEmulator: {
    width: '350px',
    height: '100%',
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow16,
    position: 'relative',
  }
});

interface DevHarnessProps {
  children: React.ReactNode;
}

export const DevHarness: React.FC<DevHarnessProps> = ({ children }) => {
  const styles = useStyles();
  const [showHarness, setShowHarness] = useState(true);

  if (!showHarness) return <>{children}</>;

  return (
    <FluentProvider theme={webLightTheme}>
      <div className={styles.harness}>
        <div className={styles.toolbar}>
          <Button size="small" onClick={() => setShowHarness(false)}>Hide Harness</Button>
          <div style={{ flex: 1 }} />
          <span>Dev Harness (Excel Mock)</span>
        </div>
        <div className={styles.content}>
          <div className={styles.taskPaneEmulator}>
            {children}
          </div>
        </div>
      </div>
    </FluentProvider>
  );
};
