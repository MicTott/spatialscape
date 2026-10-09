import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/** In development, a gitignored public/datasets.local.json (local bundles, 127.0.0.1 URLs) replaces the public registry. */
function localRegistry(): Plugin {
  const file = resolve(__dirname, "public/datasets.local.json");
  return {
    name: "spatialscape-local-registry",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split("?")[0] === "/datasets.json" && existsSync(file)) {
          res.setHeader("Content-Type", "application/json");
          res.end(readFileSync(file));
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), localRegistry()],
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
