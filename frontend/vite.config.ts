import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In dev, /api is proxied to Django so there is no CORS to configure.
// In production (Vercel) set VITE_API_URL to the backend origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    coverage: { provider: 'v8', include: ['src/**/*.{ts,tsx}'], exclude: ['src/main.tsx', 'src/test/**', 'src/**/*.test.*'] },
  },
})
