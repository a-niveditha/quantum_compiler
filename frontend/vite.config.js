import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dashboard calls the Python API (backend/api/server.py) through /api.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
});
