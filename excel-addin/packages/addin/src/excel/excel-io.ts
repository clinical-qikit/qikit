/* global Excel */

export async function getSelectedRangeValues(): Promise<{ values: any[][], address: string }> {
  return await Excel.run(async (context) => {
    const range = context.workbook.getSelectedRange();
    range.load('values, address');
    await context.sync();
    return {
      values: range.values,
      address: range.address
    };
  });
}

export async function writeToNewSheet(sheetName: string, data: any[][]): Promise<void> {
  await Excel.run(async (context) => {
    const sheet = context.workbook.worksheets.add(sheetName);
    const range = sheet.getRangeByIndexes(0, 0, data.length, data[0].length);
    range.values = data;
    sheet.activate();
    await context.sync();
  });
}
