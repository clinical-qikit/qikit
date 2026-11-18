import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import mkcert from 'vite-plugin-mkcert'
import { resolve } from 'path'
import { packageVersion } from './scripts/manifest.mjs'

// Content Security Policy for the published pages (added at build time only; the dev
// server needs inline scripts and a websocket for hot reload). GitHub Pages cannot send
// headers, so it is a <meta> tag.
//  - script-src: our own files, and Office.js. Office.js loads its host files and its
//    telemetry module from appsforoffice.microsoft.com, and MicrosoftAjax.js from
//    ajax.aspnetcdn.com. Its one `new Function` has a fallback, so no 'unsafe-eval'.
//  - style-src 'unsafe-inline': Fluent UI (Griffel) inserts <style> elements at runtime.
//  - connect-src: our code makes no requests. Office.js fetches from its own CDN and,
//    in Excel desktop, from the virtual host document.localhost.
export const CSP = [
  "default-src 'self'",
  "script-src 'self' https://appsforoffice.microsoft.com https://ajax.aspnetcdn.com",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' https://appsforoffice.microsoft.com http://document.localhost https://document.localhost",
  // Office.js tries to frame Microsoft's telemetry service (telemetryservice.
  // firstpartyapps.oaspapps.com); Office reports in without it, and this blocks it.
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'none'",
].join('; ')

const cspPlugin = {
  name: 'qikit-csp',
  apply: 'build' as const,
  transformIndexHtml: (html: string) =>
    html.replace('<meta charset="UTF-8" />',
      `<meta charset="UTF-8" />\n    <meta http-equiv="Content-Security-Policy" content="${CSP}">`),
}

const skipMkcert =process.env.NODE_ENV === 'test' || process.env.VITE_NO_MKCERT === 'true'

export default defineConfig({
  plugins: [react(), cspPlugin, !skipMkcert ? mkcert() : null],
  root: resolve(__dirname, 'packages/addin'),
  // Relative asset paths, so one build serves from any directory (a versioned Pages
  // path, `latest/`, or an intranet server).
  base: './',
  // Icons are served next to index.html; the manifest's ribbon icon URLs point here.
  publicDir: resolve(__dirname, 'assets'),
  define: {
    __QIKIT_VERSION__: JSON.stringify(packageVersion()),
  },
  build: {
    outDir: resolve(__dirname, 'dist'),
    rollupOptions: { 
      input: {
        taskpane: resolve(__dirname, 'packages/addin/index.html'),
        // The browser demo: the task pane against a mock workbook. A separate entry so
        // its Office/Excel mocks never load in Excel.
        demo: resolve(__dirname, 'packages/addin/demo.html'),
      },
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          chart: ['chart.js', 'react-chartjs-2']
        }
      }
    },
    emptyOutDir: true,
  },
  server: {
    https: !skipMkcert,
    // Manifest sideloading expects 3000; PORT lets dev harnesses pick a free port.
    port: Number(process.env.PORT) || 3000
  },
  resolve: {
    alias: { '@qikit/engine': resolve(__dirname, 'packages/engine/src') },
  },
})
