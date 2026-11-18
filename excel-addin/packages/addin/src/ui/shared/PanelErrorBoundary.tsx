import React from 'react';
import { Button } from '@fluentui/react-components';
import { ArrowResetRegular } from '@fluentui/react-icons';
import { qikit } from '../../theme/tokens';
import { ErrorNotice } from './ErrorNotice';

interface Props {
  children: React.ReactNode;
  /** Panel name, for the error details. */
  panel?: string;
}

interface State {
  error: Error | null;
  componentStack: string | null;
}

/** Isolates a panel crash so it doesn't blank the whole task pane; "Reload panel" remounts the subtree. */
export class PanelErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Panel crashed:', error, info.componentStack);
    this.setState({ componentStack: info.componentStack ?? null });
  }

  private reset = () => this.setState({ error: null, componentStack: null });

  render() {
    const { error, componentStack } = this.state;
    if (error) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px',
          padding: '32px 20px', textAlign: 'center',
        }}>
          <ErrorNotice
            error={{ message: `Something went wrong in this panel: ${error.message}`, cause: error }}
            panel={this.props.panel ?? 'unknown'}
            componentStack={componentStack}
            style={{
              padding: '10px 14px', backgroundColor: qikit.color.dangerBg, color: qikit.color.danger,
              border: `1px solid ${qikit.color.dangerBorder}`, borderRadius: qikit.radius.sm,
              fontSize: '12px', lineHeight: '1.4', width: '100%',
            }}
          />
          <Button appearance="primary" icon={<ArrowResetRegular />} onClick={this.reset}
            style={{ borderRadius: '6px' }}>
            Reload panel
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
