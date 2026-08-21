import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the Python backend so the frontend stays same-origin
// in dev exactly as it will be in production (where app.py serves the built bundle).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
