import { type APIRequestContext, type Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AxeBuilder } from "@axe-core/playwright";

async function person(
  request: APIRequestContext,
  first = "Audit",
  last = `Person${Date.now()}`,
) {
  const response = await request.post("/api/technicians", {
    data: { first_name: first, last_name: last },
  });
  expect(response.status()).toBe(201);
  return response.json();
}
async function removePerson(request: APIRequestContext, id: string) {
  const response = await request.get(`/api/technicians/${id}`);
  if (response.ok()) {
    const current = await response.json();
    expect(
      (
        await request.patch(`/api/technicians/${id}`, {
          data: {
            expected_record_version: current.record_version,
            status: "INACTIVE",
          },
        })
      ).status(),
    ).toBe(200);
  }
}
async function noOverflow(page: Page) {
  expect
    .soft(
      await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        offenders: [...document.querySelectorAll("main *")]
          .filter(
            (e) => e.getBoundingClientRect().right > window.innerWidth + 1,
          )
          .map((e) => e.tagName + "." + e.className)
          .slice(0, 15),
      })),
    )
    .toEqual({ overflow: 0, offenders: [] });
}
async function accessible(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect
    .soft(
      results.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        nodes: v.nodes.map((n) => ({
          target: n.target,
          summary: n.failureSummary,
        })),
      })),
    )
    .toEqual([]);
}
test.beforeEach(async ({ page }) => {
  await page.route("**/*", (route) =>
    ["127.0.0.1", "localhost"].includes(new URL(route.request().url()).hostname)
      ? route.continue()
      : route.abort(),
  );
});
for (const [width, height] of [
  [1920, 1080],
  [1440, 900],
  [1366, 768],
  [1024, 768],
]) {
  test(`long content, keyboard dialogs and accessibility at ${width}x${height}`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width, height });
    const t = await person(request, "A".repeat(100), "B".repeat(100));
    const response = await request.post("/api/calendars", {
      data: { name: "C".repeat(130) + Date.now() },
    });
    expect(response.status()).toBe(201);
    const c = await response.json();
    try {
      await request.put(`/api/technicians/${t.id}/calendar`, {
        data: { calendar_id: c.id },
      });
      for (const url of [
        "/",
        "/technicians",
        "/calendars",
        `/technicians/${t.id}`,
      ]) {
        await page.goto(url);
        await expect(page.getByText("Loading workspace")).toHaveCount(0);
        await expect(page.locator("main h1")).toBeVisible();
        await noOverflow(page);
        await accessible(page);
        if (url === `/technicians/${t.id}`) {
          // Stage 1's larger connection panel can push this heading below the fold.
          await page.locator(".gps-empty h3").scrollIntoViewIfNeeded();
          await accessible(page);
          await page.locator("main h1").scrollIntoViewIfNeeded();
        }
        if (url === "/technicians") {
          await page
            .getByRole("button", { name: "Add Technician", exact: true })
            .first()
            .click();
          await accessible(page);
          await page.keyboard.press("Escape");
        }
        if (url === "/calendars") {
          await page
            .getByRole("button", { name: `Remove ${c.name}`, exact: true })
            .click();
          await accessible(page);
          await noOverflow(page);
          await page.keyboard.press("Escape");
        }
        await page.screenshot({
          path: info.outputPath(
            `${width}-${url.split("/")[1] || "dashboard"}.png`,
          ),
          fullPage: true,
        });
      }
      await expect(
        page.getByRole("button", {
          name: "Delete Technician",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      await removePerson(request, t.id);
      expect(
        (
          await request.delete(`/api/calendars/${c.id}`, {
            data: { confirmation: "DELETE", detach_assigned: true },
          })
        ).status(),
      ).toBe(204);
    }
  });
}
test("offline API, malformed response and missing identity are recoverable", async ({
  page,
}) => {
  await page.route("**/api/technicians", (route) => route.abort());
  await page.goto("/technicians");
  await expect(page.locator("main").getByRole("alert")).toBeVisible();
  await page.unroute("**/api/technicians");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
  await page.route("**/api/technicians", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "invalid JSON",
    }),
  );
  await page.reload();
  await expect(page.locator("main").getByRole("alert")).toContainText(
    "invalid response",
  );
  await page.unroute("**/api/technicians");
  await page.goto("/technicians/00000000-0000-4000-8000-000000000000");
  await expect(page.locator("main").getByRole("alert")).toContainText(
    "Technician not found",
  );
  await expect(
    page.getByRole("button", { name: "Delete Technician", exact: true }),
  ).toHaveCount(0);
});
test("unexpected JSON shape reaches a usable error boundary", async ({
  page,
}) => {
  await page.route("**/api/technicians", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"unexpected":true}',
    }),
  );
  await page.goto("/technicians");
  await expect(
    page.getByRole("heading", { name: "Unable to display this page" }),
  ).toBeVisible();
  await page.unroute("**/api/technicians");
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Technicians", exact: true }),
  ).toBeVisible();
});
test("pilot deletion is absent and slow save locks inputs", async ({
  page,
  request,
}) => {
  const t = await person(request);
  try {
    await page.goto(`/technicians/${t.id}`);
    await expect(
      page.getByRole("button", { name: "Delete Technician", exact: true }),
    ).toHaveCount(0);
    expect((await request.get(`/api/technicians/${t.id}`)).status()).toBe(200);
    await page.route(`**/api/technicians/${t.id}`, async (route) => {
      if (route.request().method() === "PATCH") {
        await new Promise((resolve) => setTimeout(resolve, 500));
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            error: { message: "Simulated save failure" },
          }),
        });
      } else await route.continue();
    });
    await page.getByLabel("First name", { exact: true }).fill("Unsaved");
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(page.getByLabel("First name", { exact: true })).toBeDisabled();
    await expect(page.locator("main").getByRole("alert")).toContainText(
      "Simulated save failure",
    );
    await expect(page.getByLabel("First name", { exact: true })).toBeEnabled();
    await page.unroute(`**/api/technicians/${t.id}`);
    expect((await request.get(`/api/technicians/${t.id}`)).status()).toBe(200);
  } finally {
    await removePerson(request, t.id);
  }
});

test("renders 10, 50 and 250 cards with bounded list fetching", async ({
  page,
  request,
}, info) => {
  test.setTimeout(120000);
  const prefix = `Scale${Date.now()}`;
  const records: { id: string }[] = [];
  const measurements: {
    records: number;
    elapsedMs: number;
    listRequests: number;
  }[] = [];
  let requests = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/technicians") requests++;
  });
  try {
    for (const size of [10, 50, 250]) {
      while (records.length < size) {
        const start = records.length;
        const batch = await Promise.all(
          Array.from({ length: Math.min(10, size - start) }, (_, index) =>
            person(request, prefix, `Person${start + index}`),
          ),
        );
        records.push(...batch);
      }
      requests = 0;
      const start = Date.now();
      await page.goto("/technicians");
      await expect(
        page.getByRole("link", { name: new RegExp(`Open ${prefix} `) }),
      ).toHaveCount(size);
      measurements.push({
        records: size,
        elapsedMs: Date.now() - start,
        listRequests: requests,
      });
      expect(requests).toBeLessThanOrEqual(2); // Dev StrictMode may abort one initial request.
      await noOverflow(page);
    }
    await info.attach("card-render-profile", {
      body: JSON.stringify(measurements),
      contentType: "application/json",
    });
    console.log("Card rendering profile:", JSON.stringify(measurements));
  } finally {
    // The isolated E2E fixture truncates the disposable test database after this test.
  }
});
