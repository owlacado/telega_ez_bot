import { test, expect, harness } from "./fixtures";
test.use({ timezoneId: "Asia/Tokyo" });
test("canonical accounting daily weekly and current revision", async ({
  page,
  request,
}, testInfo) => {
  harness({ action: "expense_cleanup" });
  const tech = await (
    await request.post("/api/technicians", {
      data: {
        first_name: "Accounting",
        last_name: "Fictional",
      },
    })
  ).json();
  await request.patch(`/api/technicians/${tech.id}`, {
    data: { accounting_timezone: "America/Los_Angeles" },
  });
  try {
    const { today } = harness({
      action: "accounting_setup",
      technician_id: tech.id,
    });
    await page.goto(`/technicians/${tech.id}`);
    const region = page.getByRole("region", { name: "Today accounting" });
    await expect(region).toContainText(today);
    await expect(region).toContainText("$193.01");
    await expect(region).toContainText("$40.00");
    await page.getByRole("button", { name: "Daily report" }).click();
    await expect(
      page.getByRole("heading", { name: `Daily · ${today}` }),
    ).toBeVisible();
    await expect(page.locator(".accounting")).toContainText(
      "Facebook reviews: 2",
    );
    await expect(page.locator(".accounting")).toContainText(
      "Credit Card / Cash App",
    );
    await expect(
      page.getByText("<script>synthetic expense</script>").first(),
    ).toBeVisible();
    await page.getByRole("button", { name: "Weekly report" }).click();
    await expect(page.locator(".accounting details")).toHaveCount(7);
    await expect(page.locator(".accounting summary").first()).toContainText(
      "Monday",
    );
    await expect(page.locator(".accounting summary").last()).toContainText(
      "Sunday",
    );
    await page.getByRole("button", { name: "Previous week" }).click();
    await expect(page.locator(".accounting-metrics").first()).toContainText(
      "$55.00",
    );
    await page.getByRole("button", { name: "Current week" }).click();
    await expect(page.locator(".accounting-metrics").first()).toContainText(
      "$193.01",
    );
    harness({ action: "accounting_correct", technician_id: tech.id });
    await page.getByRole("button", { name: "Refresh accounting" }).click();
    await expect(page.locator(".accounting-metrics").first()).toContainText(
      "$268.01",
    );
    await page.getByRole("button", { name: "Overview", exact: true }).click();
    await expect(region).toContainText("$268.01");
    await page.screenshot({
      path: testInfo.outputPath("stage7-accounting-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 375, height: 812 });
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      )
      .toBeTruthy();
    await page.screenshot({
      path: testInfo.outputPath("stage7-accounting-mobile.png"),
      fullPage: true,
    });
  } finally {
    harness({ action: "expense_cleanup" });
    const current = await (
      await request.get(`/api/technicians/${tech.id}`)
    ).json();
    await request.delete(`/api/technicians/${tech.id}`, {
      data: { confirmation: "DELETE", expected_updated_at: current.updated_at },
    });
  }
});
