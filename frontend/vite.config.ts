import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, the API runs on 127.0.0.1:8000 and is proxied so the browser only
// ever talks to one local origin. In production the backend serves dist/.
const api = process.env.AMAAN_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Relative asset paths so the same build also works inside Electron later.
  base: "./",
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/analyze": { target: api, changeOrigin: true },
      "/health": { target: api, changeOrigin: true },
    },
  },
  build: { sourcemap: false },
});
