import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import mkcert from 'vite-plugin-mkcert'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react(), process.env.NODE_ENV !== 'test' ? mkcert() : null],
  root: resolve(__dirname, 'packages/addin'),
  build: {
    outDir: resolve(__dirname, 'dist'),
    rollupOptions: { 
      input: {
        taskpane: resolve(__dirname, 'packages/addin/taskpane.html')
      }
    },
    emptyOutDir: true,
  },
  server: { https: true, port: 3000 },
  resolve: {
    alias: { '@qikit/engine': resolve(__dirname, 'packages/engine/src') },
  },
})
