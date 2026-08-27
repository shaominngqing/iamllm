import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { writeFileSync } from 'node:fs'

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'keep-embedded-assets-directory',
      closeBundle() {
        writeFileSync(new URL('../internal/webassets/dist/.gitkeep', import.meta.url), '')
      },
    },
  ],
  define: {
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version || '0.1.0'),
  },
  base: '/',
  build: { outDir: '../internal/webassets/dist', emptyOutDir: true },
})
