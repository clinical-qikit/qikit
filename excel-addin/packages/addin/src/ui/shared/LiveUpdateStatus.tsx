import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CheckmarkCircleRegular, ErrorCircleRegular } from '@fluentui/react-icons';
import { subscribeLiveUpdateEvents, LiveUpdateEvent } from '../../excel/live-update';
import { qikit } from '../../theme/tokens';

/** Tracks the live-update binding this panel instance owns and surfaces its status. */
export function useLiveUpdateStatus() {
  const bindingIdRef = useRef<string | null>(null);
  const [linkedAddress, setLinkedAddress] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  useEffect(() => subscribeLiveUpdateEvents((event: LiveUpdateEvent) => {
    if (event.bindingId !== bindingIdRef.current) return;
    if (event.type === 'updated') {
      setMessage('Chart refreshed from source data.');
      setIsError(false);
    } else if (event.type === 'recompute-error') {
      setMessage(event.message);
      setIsError(true);
    } else if (event.type === 'source-deleted') {
      setMessage('Live link removed — the source range was deleted or moved.');
      setIsError(true);
      setLinkedAddress(null);
      bindingIdRef.current = null;
    }
  }), []);

  const activate = useCallback((bindingId: string, sourceAddress: string) => {
    bindingIdRef.current = bindingId;
    setLinkedAddress(sourceAddress);
    setMessage(null);
    setIsError(false);
  }, []);

  return { linkedAddress, message, isError, activate };
}

interface LiveUpdateStatusProps {
  linkedAddress: string | null;
  message: string | null;
  isError: boolean;
}

/** Small status line shown after "Write to Sheet": confirms the live link, then reports refresh/error events. */
export const LiveUpdateStatus: React.FC<LiveUpdateStatusProps> = ({ linkedAddress, message, isError }) => {
  if (!linkedAddress && !message) return null;
  const color = isError ? qikit.color.danger : qikit.color.brand;
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: '6px',
      margin: '0 16px 12px', fontSize: '11.5px', lineHeight: '1.4', color,
    }} role={isError ? 'alert' : 'status'}>
      <span aria-hidden="true" style={{ marginTop: '1px' }}>
        {isError ? <ErrorCircleRegular fontSize={14} /> : <CheckmarkCircleRegular fontSize={14} />}
      </span>
      <span>
        {message ?? `Chart updates automatically when ${linkedAddress} changes — while the add-in is open.`}
      </span>
    </div>
  );
};
