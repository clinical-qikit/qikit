import { createLightTheme, type Theme } from '@fluentui/react-components';
import { tealBrand } from './palette';
import { qikit } from './tokens';

export const qikitLightTheme: Theme = {
  ...createLightTheme(tealBrand),
  fontFamilyBase: qikit.font.base,
  fontFamilyMonospace: qikit.font.mono,
};
