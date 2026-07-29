import React from 'react';
import { Button } from '@fluentui/react-components';
import { ArrowResetRegular } from '@fluentui/react-icons';
import { qikit } from '../../theme/tokens';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

/** Isolates a panel crash so it doesn't blank the whole task pane; "Reload panel" remounts the subtree. */
export class PanelErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Panel crashed:', error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px',
          padding: '32px 20px', textAlign: 'center',
        }}>
          <div style={{
            padding: '10px 14px', backgroundColor: qikit.color.dangerBg, color: qikit.color.danger,
            border: `1px solid ${qikit.color.dangerBorder}`, borderRadius: qikit.radius.sm,
            fontSize: '12px', lineHeight: '1.4',
          }} role="alert">
            Something went wrong in this panel: {this.state.error.message}
          </div>
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
