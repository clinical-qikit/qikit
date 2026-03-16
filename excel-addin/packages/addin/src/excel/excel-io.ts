/* global Excel */

export async function getSelectedRangeValues(): Promise<{ values: any[][], address: string }> {
  try {
    return await Excel.run(async (context) => {
      const range = context.workbook.getSelectedRange();
      range.load('values, address');
      await context.sync();
      
      if (!range.values || range.values.length === 0) {
        throw new Error("The selected range is empty. Please select a range containing data.");
      }
      
      return {
        values: range.values,
        address: range.address
      };
    });
  } catch (error) {
    console.error("Error reading selected range:", error);
    throw new Error(`Failed to read Excel selection: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
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
    throw new Error(`Failed to write data to Excel: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
