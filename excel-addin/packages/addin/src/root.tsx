import { FluentProvider } from '@fluentui/react-components';
import { App } from './ui/App';
import { qikitLightTheme } from './theme/fluent-theme';

/** The task pane UI, themed. Shared by the Excel entry (index.tsx) and the demo (demo.tsx). */
export const Root = () => (
  <FluentProvider theme={qikitLightTheme}>
    <App />
  </FluentProvider>
);
