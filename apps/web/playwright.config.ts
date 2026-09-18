import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { randomBytes } from "node:crypto";
const databaseUrl =
  process.env.TEST_DATABASE_URL ??
  "postgresql+asyncpg://hub:hub_test_only@127.0.0.1:5437/technician_hub_test";
const parsedDatabase = new URL(
  databaseUrl.replace("postgresql+asyncpg:", "postgresql:"),
);
if (
  parsedDatabase.pathname !== "/technician_hub_test" ||
  !["127.0.0.1", "localhost", "test-db"].includes(parsedDatabase.hostname)
) {
  throw new Error(
    "Playwright requires an isolated local technician_hub_test database.",
  );
}
const python = path.resolve(
  __dirname,
  "../../.venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const running = Boolean(process.env.E2E_BASE_URL);
const scheduleKey =
  process.env.SCHEDULE_PAYLOAD_ENCRYPTION_KEY ??
  randomBytes(32).toString("base64url") + "=";
process.env.SCHEDULE_PAYLOAD_ENCRYPTION_KEY = scheduleKey;
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
    trace: "off",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: running
    ? undefined
    : [
        {
          command: `"${python}" -m uvicorn hub.main:app --host 127.0.0.1 --port 8001`,
          cwd: "../api",
          env: {
            DATABASE_URL: databaseUrl,
            APP_ENV: "test",
            ALLOWED_ORIGINS: '["http://127.0.0.1:3001"]',
            TELEGRAM_MODE: "fake",
            SCHEDULE_DELIVERY_ENABLED: "true",
            SCHEDULE_PAYLOAD_ENCRYPTION_KEY: scheduleKey,
            GOOGLE_MODE: "fake",
            GOOGLE_CALENDAR_CREDENTIAL_ENCRYPTION_KEY:
              randomBytes(32).toString("base64url") + "=",
            TELEGRAM_EXPECTED_BOT_ID: "9000001",
            TELEGRAM_EXPECTED_BOT_USERNAME: "hub_dedicated_test_bot",
          },
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
