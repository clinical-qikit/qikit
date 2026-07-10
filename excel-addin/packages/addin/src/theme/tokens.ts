// QI Kit design tokens — the single source of raw color/font/spacing values.
//
// Fluent components style themselves via the theme in fluent-theme.ts; everything
// custom (makeStyles chrome, Chart.js configs, native Excel charts in
// chart-builder.ts) imports from here. No other file should contain a hex literal.
export const qikit = {
  color: {
    brand: '#107C6C',
    brandHover: '#0E7062',
    brandPressed: '#0C6154',
    brandTint: '#E8F5F2', // icon chips, success/no-signal backgrounds
    brandTintBorder: '#BDDDD5', // borders on brand-tinted cards (tealBrand[150])

    ink: '#1B1B1F', // titles, values, emphasized text
    text: '#5C5C65', // body text
    textMuted: '#8E8E96', // section labels, hints, placeholders

    border: '#E8E6E3',
    borderStrong: '#D0CECA', // control outlines that need more contrast
    borderSubtle: '#F0F1F3',
    surface: '#FFFFFF',
    surfaceAlt: '#F6F6F8', // address bars, wells, subtle fills
    shell: '#F8F9FB', // app background behind panels

    danger: '#C4314B',
    dangerBg: '#FDF2F2',
    dangerBorder: '#F0C8C8',

    note: '#7A5C1E', // annotation amber text
    noteBg: '#FDF8EE',
    noteBorder: '#E8D5A8',
  },
  // Shared by the Chart.js previews AND the native Excel charts written by
  // chart-builder.ts — importing from one place is what keeps them matching.
  chart: {
    data: '#1B1B1F',
    limit: '#94A3B8',
    grid: '#F1F5F9',
    axisText: '#8E8E96',
    signal: '#DC2626', // sigma-rule violations
    runsSignal: '#F97316', // run-rule violations
    annotation: '#F59E0B',
    warn95: '#F59E0B',
    target: '#7A6FC0', // muted violet — distinct from teal brand and signal colors
    brand: '#107C6C', // Pareto/DOE bars, CUSUM line
    accent: '#F97316', // Pareto cumulative-% line, CUSUM limit
  },
  font: {
    base: "'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif",
    mono: "'Cascadia Code', 'SF Mono', Consolas, monospace",
  },
  radius: {
    sm: '4px',
    md: '6px',
    lg: '8px',
  },
  space: {
    xs: '4px',
    sm: '8px',
    md: '12px',
    lg: '16px',
  },
} as const;
