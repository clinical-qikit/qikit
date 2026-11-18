// The browser demo (demo.html): the task pane against a mock workbook, no Excel needed.
// dev-harness installs mock `Office` and `Excel` globals when it is imported, so it must
// never be imported by the Excel entry (index.tsx); there it would replace the real ones.
import { createRoot } from 'react-dom/client';
import { DevHarness } from './dev-harness';
import { Root } from './root';

const container = document.getElementById('root');
if (container) {
  createRoot(container).render(
    <DevHarness>
      <Root />
    </DevHarness>
  );
}
