// The task pane entry (index.html), loaded by Excel. Opened anywhere else (a browser, or
// with Office.js blocked) it says so and points at the demo instead.
//
// Do not import dev-harness here: it replaces the Office and Excel globals with mocks.
import { createRoot, Root as ReactRoot } from 'react-dom/client';
import { Root } from './root';
import { NotInExcel } from './not-in-excel';
import { reattachLiveUpdates } from './excel/live-update';

let root: ReactRoot | null = null;
function render(node: React.ReactNode) {
  const container = document.getElementById('root');
  if (!container) return;
  root = root ?? createRoot(container);
  root.render(node);
}

if (typeof Office !== 'undefined') {
  // Excel can take a few seconds to report in; wait for it rather than guessing.
  Office.onReady((info) => {
    if (info.host === Office.HostType.Excel) {
      render(<Root />);
      void reattachLiveUpdates();
    } else {
      render(<NotInExcel host={info.host ? String(info.host) : null} />);
    }
  });
} else {
  // Office.js failed to load (offline, or blocked by a network filter).
  render(<NotInExcel host={null} officeMissing />);
}
