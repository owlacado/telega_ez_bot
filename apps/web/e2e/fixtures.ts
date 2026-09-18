import { test as base, expect } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import path from "node:path";
const root = path.resolve(__dirname, "../../..");
export function harness(payload: Record<string, unknown>) {
  const executable = path.join(
    root,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const result = spawnSync(
    executable,
    [path.join(root, "scripts/telegram_e2e.py")],
    {
      cwd: root,
      input: JSON.stringify(payload),
      encoding: "utf8",
      env: process.env,
    },
  );
  if (result.status !== 0)
    throw new Error(result.stderr || "Isolated test harness failed");
  return result.stdout.trim() ? JSON.parse(result.stdout) : null;
}
export const test = base.extend({
  page: async ({ page, baseURL }, provide) => {
    const username = `e2e-${randomBytes(6).toString("hex")}`;
    const password = randomBytes(32).toString("base64url");
    harness({ action: "bootstrap", username, password });
    try {
      await page.route("**/*", (route) =>
        ["127.0.0.1", "localhost"].includes(
          new URL(route.request().url()).hostname,
        )
          ? route.continue()
          : route.abort(),
      );
      await page.goto("/");
      await expect(page).toHaveURL(/\/login$/);
      await page.getByLabel("Username").fill(username);
      await page.getByLabel("Password").fill(password);
      await page.getByRole("button", { name: "Sign in" }).click();
      // The form has serialized its submission. Clear before a failing matcher
      // captures the login DOM, not just during fixture teardown.
      await page.locator('input[type="password"]').evaluateAll((inputs) => {
        for (const input of inputs) (input as HTMLInputElement).value = "";
      });
      await expect(page).toHaveURL(baseURL + "/");
      const session = await (await page.request.get("/api/auth/me")).json();
      await page.context().setExtraHTTPHeaders({
        Origin: baseURL!,
        "X-Hub-Request": "1",
        "X-CSRF-Token": session.csrf_token,
      });
      await provide(page);
    } finally {
      // Playwright failure snapshots can include password input values.
      // Clear ephemeral credentials before artifact capture during teardown.
      await page
        .locator('input[type="password"]')
        .evaluateAll((inputs) => {
          for (const input of inputs) (input as HTMLInputElement).value = "";
        })
        .catch(() => {});
      harness({ action: "cleanup", username });
    }
  },
  request: async ({ page }, provide) => provide(page.request),
});
export { expect };
