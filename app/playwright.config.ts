import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:5173", headless: true, viewport: { width: 1400, height: 900 } },
  webServer: [
    {
      command: "../python/.venv/bin/spatialscape serve ../examples --port 8787",
      url: "http://127.0.0.1:8787/synthetic/manifest.json",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    // The production build, not the dev server: a cold Vite dev server re-optimizes dependencies on first
    // use and reloads the page mid-test. Locally a running dev server on 5173 is reused instead.
    { command: "npx vite build && npx vite preview --port 5173 --strictPort --host 127.0.0.1", url: "http://127.0.0.1:5173", reuseExistingServer: true, timeout: 180_000 },
  ],
});
