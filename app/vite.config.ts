import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  worker: { format: "es" },
  server: {
    port: 5173,
    strictPort: false,
    // in dev, registry entries with relative urls (e.g. examples/synthetic) are served by `spatialscape serve examples`
    proxy: { "/examples": { target: "http://127.0.0.1:8787", changeOrigin: true, rewrite: (p: string) => p.replace(/^\/examples/, "") } },
  },
  build: { target: "es2022", sourcemap: true, chunkSizeWarningLimit: 2000 },
});
