import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Built to dist/ and served by FastAPI at /. Dev server proxies API to :8000.
export default defineConfig({
  base: "/",
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/run": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
