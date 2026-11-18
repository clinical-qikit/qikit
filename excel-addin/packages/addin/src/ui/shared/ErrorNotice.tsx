import React, { useState } from 'react';
import { Button } from '@fluentui/react-components';
import { CopyRegular, CheckmarkRegular } from '@fluentui/react-icons';
import { qikit } from '../../theme/tokens';
import { ErrorState, copyText, errorDetails, errorMessage } from './error-report';

interface Props {
  error: ErrorState;
  /** Panel name, for the details. */
  panel: string;
  /** The panel's own error box style, so the notice sits where errors always have. */
  className?: string;
  style?: React.CSSProperties;
  componentStack?: string | null;
}

/** An error message with "Copy details": versions, panel and trace, for an issue. */
export const ErrorNotice: React.FC<Props> = ({ error, panel, className, style, componentStack }) => {
  const [copied, setCopied] = useState<'yes' | 'no' | null>(null);
  const [open, setOpen] = useState(false);
  if (!error) return null;
  const details = () => errorDetails({ panel, error, componentStack });

  const copy = async () => {
    const ok = await copyText(details());
    setCopied(ok ? 'yes' : 'no');
    if (!ok) setOpen(true);
  };

  return (
    <div className={className} style={style} role="alert">
      <div>{errorMessage(error)}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px', flexWrap: 'wrap' }}>
        <Button size="small" appearance="subtle"
          icon={copied === 'yes' ? <CheckmarkRegular /> : <CopyRegular />}
          onClick={copy} style={{ color: 'inherit', minWidth: 0, padding: '0 4px' }}>
          {copied === 'yes' ? 'Copied' : 'Copy details'}
        </Button>
        <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
          style={{
            background: 'none', border: 'none', padding: 0, cursor: 'pointer',
            color: 'inherit', fontSize: '11px', textDecoration: 'underline', fontFamily: 'inherit',
          }}>
          {open ? 'Hide details' : 'Show details'}
        </button>
      </div>
      {copied === 'no' && (
        <div style={{ fontSize: '11px', marginTop: '4px' }}>
          Excel blocked the clipboard: select the text below and copy it.
        </div>
      )}
      {open && (
        <>
          <textarea readOnly value={details()} aria-label="Error details"
            onFocus={e => e.currentTarget.select()}
            style={{
              width: '100%', height: '120px', marginTop: '6px', fontFamily: qikit.font.mono,
              fontSize: '10px', color: qikit.color.ink, border: `1px solid ${qikit.color.border}`,
              borderRadius: qikit.radius.sm, resize: 'vertical',
            }} />
          <div style={{ fontSize: '11px', marginTop: '4px', color: qikit.color.text }}>
            Nothing is sent. Paste it into an issue at github.com/clinical-qikit/qikit/issues;
            check it first, since a message can name a column from your sheet.
          </div>
        </>
      )}
    </div>
  );
};
