/* global Excel */

export interface RangeData {
  values: any[][];
  address: string;
  /** Number formats, same shape as values; what tells a date cell from a number. */
  numberFormats?: any[][];
  /** Worksheet row number of the range's first row. */
  firstRow: number;
}

/** The first row number in an address such as "Sheet1!B5:D20" or "'My sheet'!A1". */
export function firstRowOf(address: string): number {
  const cells = address.includes('!') ? address.slice(address.lastIndexOf('!') + 1) : address;
  const m = cells.match(/^\$?[A-Z]+\$?(\d+)/i);
  return m ? parseInt(m[1], 10) : 1;
}

/** A friendlier error that keeps the original (with its Office.js code) as `cause`. */
function wrapError(message: string, error: unknown): Error {
  const wrapped = new Error(`${message}: ${error instanceof Error ? error.message : 'Unknown error'}`);
  (wrapped as Error & { cause?: unknown }).cause = error;
  return wrapped;
}

export async function getSelectedRangeValues(): Promise<RangeData> {
  try {
    return await Excel.run(async (context) => {
      const range = context.workbook.getSelectedRange();
      range.load('values, address, numberFormat');
      await context.sync();

      if (!range.values || range.values.length === 0) {
        throw new Error("The selected range is empty. Please select a range containing data.");
      }

      return {
        values: range.values,
        address: range.address,
        numberFormats: range.numberFormat,
        firstRow: firstRowOf(range.address),
      };
    });
  } catch (error) {
    console.error("Error reading selected range:", error);
    throw wrapError('Failed to read Excel selection', error);
  }
}

/** Overwrites an existing sheet's output table at A1, clearing rows left over from a previous, longer write. */
export async function writeToSheetRange(
  sheetName: string,
  data: any[][],
  previousRowCount: number,
): Promise<{ rangeAddress: string }> {
  try {
    if (!data || data.length === 0 || !data[0] || data[0].length === 0) {
      throw new Error("No data provided to write to the sheet.");
    }

    return await Excel.run(async (context) => {
      const sheet = context.workbook.worksheets.getItem(sheetName);
      const range = sheet.getRangeByIndexes(0, 0, data.length, data[0].length);
      range.values = data;

      if (previousRowCount > data.length) {
        const staleRange = sheet.getRangeByIndexes(data.length, 0, previousRowCount - data.length, data[0].length);
        staleRange.clear(Excel.ClearApplyTo.contents);
      }

      range.load("address");
      await context.sync();

      return { rangeAddress: range.address };
    });
  } catch (error) {
    console.error("Error writing to sheet range:", error);
    throw wrapError('Failed to write data to Excel', error);
  }
}

/**
 * Write a table to a new sheet, apply per-column number formats (null leaves a column
 * as General), select it, and read it back as getSelectedRangeValues would.
 */
export async function writeSampleSheet(
  sheetName: string,
  data: any[][],
  columnFormats: (string | null)[],
): Promise<RangeData> {
  const { sheetName: finalName } = await writeToNewSheet(sheetName, data);
  return await Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.getItem(finalName);
    columnFormats.forEach((fmt, col) => {
      if (fmt && data.length > 1) {
        const cells = sheet.getRangeByIndexes(1, col, data.length - 1, 1);
        cells.numberFormat = Array.from({ length: data.length - 1 }, () => [fmt]);
      }
    });
    const range = sheet.getRangeByIndexes(0, 0, data.length, data[0].length);
    range.format.autofitColumns();
    range.select();
    range.load('values, address, numberFormat');
    await context.sync();
    return {
      values: range.values,
      address: range.address,
      numberFormats: range.numberFormat,
      firstRow: firstRowOf(range.address),
    };
  });
}

export async function writeToNewSheet(sheetName: string, data: any[][]): Promise<{ sheetName: string, rangeAddress: string }> {
  try {
    if (!data || data.length === 0 || !data[0] || data[0].length === 0) {
      throw new Error("No data provided to write to the sheet.");
    }

    return await Excel.run(async (context) => {
      // Create a unique sheet name to avoid conflicts
      const sheets = context.workbook.worksheets;
      sheets.load("items/name");
      await context.sync();
      
      let finalSheetName = sheetName;
      let counter = 1;
      while (sheets.items.some(s => s.name === finalSheetName)) {
        finalSheetName = `${sheetName} (${counter})`;
        counter++;
      }

      const sheet = context.workbook.worksheets.add(finalSheetName);
      const range = sheet.getRangeByIndexes(0, 0, data.length, data[0].length);
      range.values = data;
      sheet.activate();
      range.load("address");
      await context.sync();

      return {
        sheetName: finalSheetName,
        rangeAddress: range.address
      };
    });
  } catch (error) {
    console.error("Error writing to new sheet:", error);
    throw wrapError('Failed to write data to Excel', error);
  }
}
