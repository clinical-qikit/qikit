import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import mkcert from 'vite-plugin-mkcert'

export default defineConfig({
  plugins: [react(), process.env.NODE_ENV !== 'test' ? mkcert() : null],
  root: 'packages/addin',
  build: {
    outDir: '../../dist',
    rollupOptions: { input: 'taskpane.html' },
  },
  server: { https: true, port: 3000 },
  resolve: {
    alias: { '@qikit/engine': '../engine/src' },
  },
})
