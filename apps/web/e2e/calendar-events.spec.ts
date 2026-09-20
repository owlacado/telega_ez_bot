import { test, expect, harness } from "./fixtures";

test("event scope upgrade, jobs, filtering, preview, refresh and technician isolation", async ({
  page,
  request,
}, testInfo) => {
  harness({ action: "google_reset" });
  const first = await (
    await request.post("/api/technicians", {
      data: { first_name: "Event", last_name: "Acceptance" },
    })
  ).json();
  const second = await (
    await request.post("/api/technicians", {
      data: { first_name: "Other", last_name: "Event" },
    })
  ).json();
  try {
    await page.goto("/calendars");
    await page
      .getByRole("button", { name: "Connect Google Calendar", exact: true })
      .click();
    await expect(page.getByText("Connected", { exact: true })).toBeVisible();
    const calendars = await (await request.get("/api/calendars")).json();
    const calendar = calendars.find(
      (c: { name: string }) => c.name === "GA - Atlanta",
    );
    expect(
      (
        await request.put(`/api/technicians/${first.id}/calendar`, {
          data: { calendar_id: calendar.id },
        })
      ).ok(),
    ).toBeTruthy();
    await page.goto(`/technicians/${first.id}`);
    await expect(
      page.getByText("Google Calendar event access is required."),
    ).toBeVisible();
    await page.getByRole("link", { name: "Grant Event Access" }).click();
    await page.getByRole("button", { name: "Grant Event Access" }).click();
    await expect(page.getByText(/Google event access available/)).toBeVisible();
    await page.goto(`/technicians/${first.id}`);
    const jobs = page.getByRole("region", { name: "Today's Jobs" });
    await expect(
      jobs.getByText("1. Furnace (old customer) didnt buy", { exact: true }),
    ).toBeVisible();
    await expect(jobs.getByText("08:00", { exact: true })).toBeVisible();
    await expect(
      jobs.getByText("Unnumbered repair", { exact: true }),
    ).toBeVisible();
    await expect(jobs.getByText("CANCEL - job", { exact: true })).toHaveCount(
      0,
    );
    await expect(jobs.getByText("fake job", { exact: true })).toHaveCount(0);
    await jobs.getByText("Job notes").first().click();
    await expect(
      jobs
        .getByText("Customer note: do not cancel this valid appointment.")
        .first(),
    ).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("stage3-todays-jobs.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: /Preview .*Schedule/ }).click();
    const modal = page.getByRole("dialog", {
      name: "Next Work Day Schedule Preview",
    });
    await expect(modal.getByText("1. Furnace", { exact: true })).toBeVisible();
    await expect(modal).toContainText("Telegram delivery");
    await page.screenshot({
      path: testInfo.outputPath("stage3-schedule-preview.png"),
      fullPage: true,
    });
    const preview = await (
      await request.get(`/api/technicians/${first.id}/calendar/next-schedule`)
    ).json();
    expect(preview.operational_date).toBeTruthy();
    await modal.getByRole("button", { name: "Close", exact: true }).click();
    await jobs.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(jobs.getByText(/Furnace.*refreshed/)).toBeVisible();
    await page.goto(`/technicians/${second.id}`);
    await expect(
      page.getByText("No calendar assigned.", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/Furnace/)).toHaveCount(0);
  } finally {
    for (const tech of [first, second]) {
      const current = await request.get(`/api/technicians/${tech.id}`);
      if (current.ok())
        await request.delete(`/api/technicians/${tech.id}`, {
          data: {
            confirmation: "DELETE",
            expected_record_version: (await current.json()).record_version,
          },
        });
    }
    harness({ action: "google_reset" });
  }
});
for (const day of ["2026-09-19", "2026-09-20"]) {
  test(`weekend ${day} previews Monday without browser timezone conversion`, async ({
    page,
    request,
  }) => {
    const tech = await (
      await request.post("/api/technicians", {
        data: { first_name: "Weekend", last_name: "Preview" },
      })
    ).json();
    const value = {
      technician: { id: tech.id, first_name: "Weekend", last_name: "Preview" },
      state: "READY",
      calendar: { id: "synthetic", name: "Test calendar" },
      operational_date: day,
      next_schedule_date: "2026-09-21",
      timezone: "America/New_York",
      display_semantics: "CALENDAR_WALL_CLOCK",
      jobs: [],
      warnings: [],
      last_fetched_at: "2026-09-19T12:00:00Z",
    };
    await page.route(`**/api/technicians/${tech.id}/calendar/today`, (route) =>
      route.fulfill({ json: value }),
    );
    await page.route(
      `**/api/technicians/${tech.id}/calendar/next-schedule`,
      (route) =>
        route.fulfill({ json: { ...value, operational_date: "2026-09-21" } }),
    );
    try {
      await page.goto(`/technicians/${tech.id}`);
      await page
        .getByRole("button", { name: "Preview Monday’s Schedule" })
        .click();
      await expect(page.getByRole("dialog")).toContainText("Monday, Sep 21");
      await expect(page.getByRole("dialog")).toContainText(
        "No scheduled jobs.",
      );
    } finally {
      const current = await request.get(`/api/technicians/${tech.id}`);
      await request.delete(`/api/technicians/${tech.id}`, {
        data: {
          confirmation: "DELETE",
          expected_record_version: (await current.json()).record_version,
        },
      });
    }
  });
}
