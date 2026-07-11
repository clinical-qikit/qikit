/** 0-based column index → Excel column letter (0 → "A", 26 → "AA"). */
export function colLetter(i: number): string {
  let r = '';
  let n = i;
  do { r = String.fromCharCode(65 + (n % 26)) + r; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return r;
}
