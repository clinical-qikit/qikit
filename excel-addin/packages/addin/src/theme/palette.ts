import type { BrandVariants } from '@fluentui/react-components';

// Clinical teal brand ramp, anchored so brand[80] is the QI Kit teal #107C6C.
// Fluent's light theme maps colorBrandBackground → 80, hover → 70, pressed → 60,
// which preserves the existing darker-on-hover behavior (#0A6B5C era).
export const tealBrand: BrandVariants = {
  10: '#031512',
  20: '#05231E',
  30: '#073129',
  40: '#094035',
  50: '#0B4F41',
  60: '#0C6154',
  70: '#0E7062',
  80: '#107C6C',
  90: '#268A7A',
  100: '#3F9889',
  110: '#57A698',
  120: '#70B4A7',
  130: '#89C1B6',
  140: '#A3CFC6',
  150: '#BDDDD5',
  160: '#D7EBE5',
};
