import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite dev server config. Runs entirely on the local machine.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: false,
  },
})
