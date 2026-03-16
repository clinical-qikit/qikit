import React from 'react';
import { createRoot } from 'react-dom/client';
import { FluentProvider, webLightTheme } from '@fluentui/react-components';

const App = () => {
  return (
    <FluentProvider theme={webLightTheme}>
      <div>
        <h1>QI Kit Task Pane</h1>
      </div>
    </FluentProvider>
  );
};

// Initialize Office JS
Office.onReady(() => {
  const container = document.getElementById('root');
  if (container) {
    const root = createRoot(container);
    root.render(<App />);
  }
});

// For development in browser without Office.js context:
if (!window.Office || !window.Office.context) {
  const container = document.getElementById('root');
  if (container) {
    const root = createRoot(container);
    root.render(<App />);
  }
}
