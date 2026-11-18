import { qikit } from './theme/tokens';
import { VERSION } from './version';

interface Props {
  /** The Office host that opened the page, when it is not Excel. */
  host: string | null;
  /** True when Office.js itself never loaded. */
  officeMissing?: boolean;
}

/** Shown when the task pane page is opened outside Excel. */
export const NotInExcel = ({ host, officeMissing }: Props) => (
  <div style={{
    maxWidth: '420px', margin: '0 auto', padding: '40px 20px',
    fontSize: '14px', lineHeight: 1.5, color: qikit.color.ink,
  }}>
    <h1 style={{ fontSize: '18px', margin: '0 0 12px' }}>QI Kit for Excel</h1>
    <p style={{ margin: '0 0 12px' }}>
      {host
        ? `This add-in runs in Excel; it was opened in ${host}.`
        : officeMissing
          ? 'This page is the QI Kit task pane, and runs inside Excel. Office.js did not load, so it cannot reach Excel from here.'
          : 'This page is the QI Kit task pane, and runs inside Excel.'}
    </p>
    <p style={{ margin: '0 0 12px' }}>
      <a href="./demo.html" style={{ color: qikit.color.brand }}>Try the demo</a> to use it
      in the browser with sample data, or see the{' '}
      <a href="https://github.com/clinical-qikit/qikit/blob/main/docs/deployment.md"
        style={{ color: qikit.color.brand }}>install guide</a>.
    </p>
    <p style={{ margin: 0, fontSize: '12px', color: qikit.color.text }}>Version {VERSION}</p>
  </div>
);
