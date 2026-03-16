import React from 'react';
import { createRoot } from 'react-dom/client';
import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { App } from './ui/App';
import { DevHarness } from './dev-harness';

const Root = () => (
  <FluentProvider theme={webLightTheme}>
    <App />
  </FluentProvider>
);

// Initialize Office JS
Office.onReady((info) => {
  const container = document.getElementById('root');
  if (container) {
    const root = createRoot(container);
    // If we're not in Excel (e.g. browser dev), wrap in Harness
    if (info.host === null) {
      root.render(
        <DevHarness>
          <Root />
        </DevHarness>
      );
    } else {
      root.render(<Root />);
    }
  }
});

// For development in browser where Office.onReady might not fire as expected
// or when Office.js is not loaded at all.
setTimeout(() => {
  if (!window.Office || !window.Office.context || !window.Office.context.host) {
    const container = document.getElementById('root');
    if (container && !container.innerHTML) {
      const root = createRoot(container);
      root.render(
        <DevHarness>
          <Root />
        </DevHarness>
      );
    }
  }
}, 1000);
