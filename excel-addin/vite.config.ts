import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import mkcert from 'vite-plugin-mkcert'
import { resolve } from 'path'
import { packageVersion } from './scripts/manifest.mjs'

const skipMkcert = process.env.NODE_ENV === 'test' || process.env.VITE_NO_MKCERT === 'true'

export default defineConfig({
  plugins: [react(), !skipMkcert ? mkcert() : null],
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
