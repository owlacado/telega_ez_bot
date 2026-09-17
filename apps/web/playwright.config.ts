import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
const databaseUrl =
  "postgresql+asyncpg://hub:hub_test_only@127.0.0.1:5437/technician_hub_test";
const python = path.resolve(
  __dirname,
  "../../.venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const running = Boolean(process.env.E2E_BASE_URL);
export default defineConfig({
  testDir: "./e2e",
  outputDir: `test-results/${running ? "production" : "development"}`,
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3001",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: running
    ? undefined
    : [
        {
          command: `"${python}" -m uvicorn hub.main:app --host 127.0.0.1 --port 8001`,
          cwd: "../api",
          env: { DATABASE_URL: databaseUrl, APP_ENV: "test" },
          url: "http://127.0.0.1:8001/api/health",
          reuseExistingServer: false,
        },
        {
          command: "npm run dev -- --port 3001",
          env: {
            API_INTERNAL_URL: "http://127.0.0.1:8001",
            NEXT_TELEMETRY_DISABLED: "1",
          },
          url: "http://127.0.0.1:3001",
          reuseExistingServer: false,
          timeout: 120_000,
        },
      ],
});
