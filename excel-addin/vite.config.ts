import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import mkcert from 'vite-plugin-mkcert'
import { resolve } from 'path'

const skipMkcert = process.env.NODE_ENV === 'test' || process.env.VITE_NO_MKCERT === 'true'

export default defineConfig({
  plugins: [react(), !skipMkcert ? mkcert() : null],
  root: resolve(__dirname, 'packages/addin'),
  build: {
    outDir: resolve(__dirname, 'dist'),
    rollupOptions: { 
      input: {
        taskpane: resolve(__dirname, 'packages/addin/taskpane.html')
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
    port: 3000 
  },
  resolve: {
    alias: { '@qikit/engine': resolve(__dirname, 'packages/engine/src') },
  },
})
