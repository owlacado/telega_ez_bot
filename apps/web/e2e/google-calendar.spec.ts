import { expect, test, harness } from "./fixtures";

test("fake Google connection, scan, assignment, exclusion, restore and disconnect", async ({
  page,
  request,
}) => {
  harness({ action: "google_reset" });
  const created = await request.post("/api/technicians", {
    data: { first_name: "Google", last_name: "Acceptance" },
  });
  expect(created.status()).toBe(201);
  const technician = await created.json();
  try {
    await page.goto("/calendars");
    await expect(
      page.getByRole("button", { name: "Scan Google Calendars" }),
    ).toBeDisabled();
    await page
      .getByRole("button", { name: "Connect Google Calendar", exact: true })
      .click();
    await expect(page.getByText("Connected", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(/\/calendars$/);
    await page.getByRole("button", { name: "Scan Google Calendars" }).click();
    await expect(
      page.getByText("Scan complete. 3 calendars discovered."),
    ).toBeVisible();
    const atlanta = page.getByRole("row").filter({ hasText: "GA - Atlanta" });
    await atlanta.getByRole("button", { name: "Assign", exact: true }).click();
    await page
      .getByLabel("Assigned technician", { exact: true })
      .selectOption(technician.id);
    await page.getByRole("button", { name: "Save assignment" }).click();
    await expect(
      atlanta.getByRole("link", { name: "Google Acceptance" }),
    ).toBeVisible();
    await atlanta.getByRole("link", { name: "Google Acceptance" }).click();
    const dropdown = page.getByLabel("Assigned calendar", { exact: true });
    await expect(dropdown.locator("option:checked")).toHaveText("GA - Atlanta");
    await dropdown.selectOption({ label: "GA - Savannah" });
    await expect(dropdown.locator("option:checked")).toHaveText(
      "GA - Savannah",
    );
    await page.goto("/calendars");
    const savannah = page.getByRole("row").filter({ hasText: "GA - Savannah" });
    await expect(
      savannah.getByRole("link", { name: "Google Acceptance" }),
    ).toBeVisible();
    await savannah
      .getByRole("button", { name: "Remove GA - Savannah" })
      .click();
    const modal = page.getByRole("dialog", {
      name: "Remove from Technician Hub?",
    });
    await expect(modal).toContainText("will become unassigned");
    await expect(modal).toContainText(
      "Nothing will be deleted from Google Calendar",
    );
    await modal
      .getByRole("button", { name: "Remove calendar", exact: true })
      .click();
    await expect(savannah).toHaveCount(0);
    expect(
      (await (await request.get(`/api/technicians/${technician.id}`)).json())
        .calendar,
    ).toBeNull();
    await page.getByRole("button", { name: "Scan Google Calendars" }).click();
    await expect(
      page.getByText("Scan complete. 3 calendars discovered."),
    ).toBeVisible();
    await expect(savannah).toHaveCount(0);
    await page.getByRole("button", { name: "Excluded Calendars (1)" }).click();
    await page.getByRole("button", { name: "Restore GA - Savannah" }).click();
    await expect(savannah).toBeVisible();
    await page.getByRole("button", { name: "Disconnect", exact: true }).click();
    await page.getByRole("button", { name: "Confirm disconnect" }).click();
    await expect(
      page.getByRole("button", { name: "Scan Google Calendars" }),
    ).toBeDisabled();
    await expect(savannah).toContainText("Unavailable");
    const status = await (
      await request.get("/api/calendar-connections/google")
    ).json();
    expect(status.status).toBe("DISCONNECTED");
    expect(JSON.stringify(status)).not.toMatch(
      /fake-access|fake-refresh|encrypted_refresh_token/,
    );
    expect(
      await page.evaluate(() =>
        JSON.stringify({
          local: { ...localStorage },
          session: { ...sessionStorage },
        }),
      ),
    ).not.toMatch(/fake-access|fake-refresh|fake-code/);
    await page
      .getByRole("button", { name: "Reconnect Google Calendar" })
      .click();
    await expect(page.getByText("Connected", { exact: true })).toBeVisible();
    await expect(savannah).toContainText("Available");
  } finally {
    const current = await request.get(`/api/technicians/${technician.id}`);
    if (current.ok())
      await request.delete(`/api/technicians/${technician.id}`, {
        data: {
          confirmation: "DELETE",
          expected_record_version: (await current.json()).record_version,
        },
      });
    harness({ action: "google_reset" });
  }
});

test("calendar search, filters and malicious metadata at 10/50/250/1000 rows", async ({
  page,
}, info) => {
  let rows: object[] = [];
  await page.route("**/api/calendars", (route) =>
    route.fulfill({ json: rows }),
  );
  await page.route("**/api/technicians", (route) =>
    route.fulfill({ json: [] }),
  );
  const measurements: object[] = [];
  for (const size of [10, 50, 250, 1000]) {
    rows = Array.from({ length: size }, (_, index) => ({
      id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      name:
        index === 0
          ? "malicious <script>alert(1)</script> [x](javascript:evil) \u05d0 \ud83d\udd27 " +
            "long".repeat(15)
          : `Audit calendar ${index}`,
      source: "GOOGLE",
      availability: index % 5 === 0 ? "UNAVAILABLE" : "AVAILABLE",
      excluded_at: null,
      assigned_technician: null,
      timezone: null,
      primary: false,
      access_role: "reader",
      last_seen_at: null,
      created_at: "2026-09-17T00:00:00Z",
      updated_at: "2026-09-17T00:00:00Z",
    }));
    const start = Date.now();
    await page.goto("/calendars");
    await expect(page.getByRole("row")).toHaveCount(size + 1);
    const renderMs = Date.now() - start;
    const searchStart = Date.now();
    await page.getByLabel("Search calendars").fill("malicious");
    await expect(page.getByRole("row")).toHaveCount(2);
    const filterMs = Date.now() - searchStart;
    await expect(page.getByText(/malicious <script>/)).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(await page.locator('a[href^="javascript:"]').count()).toBe(0);
    await page.getByLabel("Search calendars").fill("");
    await page
      .getByRole("combobox", { name: "Filter", exact: true })
      .selectOption("Unavailable");
    await expect(page.getByRole("row")).toHaveCount(size / 5 + 1);
    measurements.push({ size, renderMs, filterMs });
  }
  await page.screenshot({
    path: info.outputPath("calendar-large-metadata.png"),
  });
  console.log("Calendar browser measurements", JSON.stringify(measurements));
});

test("OAuth callback preserves its manager session after cross-site consent navigation", async ({
  page,
  request,
  baseURL,
}) => {
  harness({ action: "google_reset" });
  try {
    const status = await (
      await request.get("/api/calendar-connections/google")
    ).json();
    const started = await request.post(
      "/api/calendar-connections/google/start",
      {
        data: {
          mode: "CONNECT",
          expected_connection_id: status.id,
          expected_generation: status.generation,
        },
      },
    );
    expect(started.ok()).toBeTruthy();
    const callback = new URL((await started.json()).authorization_url, baseURL)
      .href;
    const consent = new URL(baseURL!);
    consent.hostname = "localhost"; // Distinct cookie site from 127.0.0.1, still loopback only.
    consent.pathname = "/audit-synthetic-consent";
    await page.route(consent.href, (route) =>
      route.fulfill({
        contentType: "text/html",
        body: '<a id="return">Return to Technician Hub</a>',
      }),
    );
    await page.goto(consent.href);
    await page
      .locator("#return")
      .evaluate((node, target) => node.setAttribute("href", target), callback);
    await page.getByRole("link", { name: "Return to Technician Hub" }).click();
    await expect(page.getByText("Connected", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(baseURL + "/calendars");
  } finally {
    harness({ action: "google_reset" });
  }
});
