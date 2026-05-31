import path from 'node:path'
import { defineConfig } from 'vitest/config'

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
