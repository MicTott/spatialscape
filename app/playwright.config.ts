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
    },
    { command: "npx vite --port 5173 --strictPort", url: "http://127.0.0.1:5173", reuseExistingServer: true },
  ],
});
