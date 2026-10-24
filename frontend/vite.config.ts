import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, the API runs on 127.0.0.1:8000 and is proxied so the browser only
// ever talks to one local origin. In production the backend serves dist/.
const api = process.env.AMAAN_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./", // relative asset paths: the backend serves the build from any folder
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // Every backend route the web app calls (see src/lib/api.ts).
    proxy: Object.fromEntries(
      ["/analyze", "/health", "/import", "/whatsapp", "/ai", "/phone"].map((p) => [p, { target: api, changeOrigin: true }]),
    ),
  },
  build: { sourcemap: false },
});
