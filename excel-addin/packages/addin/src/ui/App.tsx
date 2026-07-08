import React, { useState } from 'react';
import { makeStyles } from '@fluentui/react-components';
import {
  DataBarVerticalRegular, DataBarVerticalFilled,
  BeakerRegular, BeakerFilled,
  DataUsageRegular, DataUsageFilled,
  ArrowTrendingRegular, ArrowTrendingFilled,
} from '@fluentui/react-icons';
import { SpcPanel } from './spc/SpcPanel';
import { DoeWizard } from './doe/DoeWizard';
import { ParetoPanel } from './pareto/ParetoPanel';
import { BChartPanel } from './bchart/BChartPanel';

const useStyles = makeStyles({
  shell: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    backgroundColor: '#f8f9fb',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '14px 16px 0 16px',
  },
  logoMark: {
    width: '28px',
    height: '28px',
    borderRadius: '6px',
    background: 'linear-gradient(135deg, #107C6C, #0A6B5C)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#fff',
    fontWeight: '700',
    fontSize: '13px',
    letterSpacing: '-0.5px',
    flexShrink: 0,
  },
  title: {
    fontSize: '15px',
    fontWeight: '600',
    color: '#1B1B1F',
    letterSpacing: '-0.3px',
  },
  nav: {
    display: 'flex',
    gap: '2px',
    padding: '12px 16px 0 16px',
    overflowX: 'auto',
  },
  navItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '5px',
    padding: '7px 11px',
    borderRadius: '8px 8px 0 0',
    border: 'none',
    cursor: 'pointer',
    fontSize: '12px',
    fontWeight: '500',
    fontFamily: 'inherit',
    transition: 'all 0.15s ease',
    position: 'relative',
    color: '#6b7280',
    backgroundColor: 'transparent',
    whiteSpace: 'nowrap',
    flexShrink: 0,
    '&:hover': {
      color: '#107C6C',
      backgroundColor: 'rgba(16, 124, 108, 0.04)',
    },
  },
  navItemActive: {
    color: '#107C6C',
    backgroundColor: '#ffffff',
    boxShadow: '0 -1px 3px rgba(0,0,0,0.04)',
    '&::after': {
      content: '""',
      position: 'absolute',
      bottom: '0',
      left: '10px',
      right: '10px',
      height: '2px',
      backgroundColor: '#107C6C',
      borderRadius: '2px 2px 0 0',
    },
  },
  navIcon: {
    fontSize: '15px',
    display: 'flex',
  },
  content: {
    flex: 1,
    overflowY: 'auto',
    backgroundColor: '#ffffff',
    borderTop: '1px solid #e8e6e3',
  },
});

type TabKey = 'spc' | 'doe' | 'pareto' | 'bchart';

const TABS: { key: TabKey; label: string; Icon: React.FC; IconActive: React.FC }[] = [
  { key: 'spc',    label: 'SPC',                    Icon: DataBarVerticalRegular, IconActive: DataBarVerticalFilled },
  { key: 'doe',    label: 'Planned Experimentation', Icon: BeakerRegular,          IconActive: BeakerFilled          },
  { key: 'pareto', label: 'Pareto',                  Icon: DataUsageRegular,       IconActive: DataUsageFilled       },
  { key: 'bchart', label: 'Bernoulli CUSUM',         Icon: ArrowTrendingRegular,   IconActive: ArrowTrendingFilled   },
];

export const App: React.FC = () => {
  const styles = useStyles();
  const [tab, setTab] = useState<TabKey>('spc');

  return (
    <div className={styles.shell}>
      <div className={styles.header}>
        <div className={styles.logoMark}>QI</div>
        <span className={styles.title}>QI Kit</span>
      </div>
      <nav className={styles.nav}>
        {TABS.map(({ key, label, Icon, IconActive }) => (
          <button
            key={key}
            className={`${styles.navItem} ${tab === key ? styles.navItemActive : ''}`}
            onClick={() => setTab(key)}
          >
            <span className={styles.navIcon}>
              {tab === key ? <IconActive /> : <Icon />}
            </span>
            {label}
          </button>
        ))}
      </nav>
      <div className={styles.content}>
        {tab === 'spc'    && <SpcPanel />}
        {tab === 'doe'    && <DoeWizard />}
        {tab === 'pareto' && <ParetoPanel />}
        {tab === 'bchart' && <BChartPanel />}
      </div>
    </div>
  );
};
