import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@aqua/workflow-core': path.resolve(__dirname, './src/vendor/workflow-core/index.ts'),
    },
  },
  test: {
    environment: 'node',
  },
})
