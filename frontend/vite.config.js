import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    // HMR over the host-forwarded port works reliably inside Docker on
    // Windows when we tell Vite the public URL the browser will use.
    hmr: {
      clientPort: 5173,
    },
    watch: {
      // Native fs events don't fire reliably through a Windows bind-mount
      // into a Linux container — polling is slower but actually works.
      usePolling: true,
      interval: 300,
    },
  },
});
