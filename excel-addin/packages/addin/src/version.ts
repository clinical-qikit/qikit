// Replaced at build time by vite.config.ts with the qikit package version.
declare const __QIKIT_VERSION__: string | undefined;

/** The add-in's version, or "dev" where the build-time value is absent (tests). */
export const VERSION: string =
  typeof __QIKIT_VERSION__ !== 'undefined' ? __QIKIT_VERSION__ : 'dev';
