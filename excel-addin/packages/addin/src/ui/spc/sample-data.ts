// A made-up series for "Try with sample data": two years of a monthly measure that
// improves after the first year, so a new user sees what a finding looks like. It is
// written to a new sheet as real dates (serial numbers in a date format), the same
// shape a user's own data has.

/** Excel serial number of the first day of a month (UTC). */
function serial(year: number, month0: number): number {
  return Date.UTC(year, month0, 1) / 86400000 + 25569;
}

const WAITS = [
  44, 41, 46, 43, 39, 45, 42, 47, 40, 44, 43, 41,
  36, 33, 35, 31, 34, 32, 36, 30, 33, 35, 32, 34,
];

export const SAMPLE_SHEET_NAME = 'QI Kit sample';

export const SAMPLE_HEADERS = ['Month', 'Median minutes, arrival to provider (sample)'];

/** The sample table, header row first. */
export function sampleRows(): any[][] {
  return [
    SAMPLE_HEADERS,
    ...WAITS.map((y, i) => [serial(2025 + Math.floor(i / 12), i % 12), y]),
  ];
}

/** Number format per column: a date for Month, General for the values. */
export const SAMPLE_FORMATS: (string | null)[] = ['mmm yyyy', null];
