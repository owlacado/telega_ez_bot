import { test, expect, harness } from "./fixtures";
test("mobile expenses: lost response, new identical expense, manager facts", async ({
  page,
  request,
  baseURL,
}, testInfo) => {
  harness({ action: "expense_cleanup" });
  const userId = 800000000 + (Date.now() % 100000000);
  const tech = await (
    await request.post("/api/technicians", {
      data: { first_name: "Expense", last_name: "Fictional" },
    })
  ).json();
  try {
    const configured = await request.patch(`/api/technicians/${tech.id}`, {
      data: { accounting_timezone: "America/Los_Angeles" },
    });
    expect(configured.ok()).toBeTruthy();
    harness({
      action: "expense_setup",
      technician_id: tech.id,
      user_id: userId,
    });
    const issue = () =>
      harness({
        action: "expense_issue",
        user_id: userId,
        update_id: Date.now(),
        origin: baseURL,
      }).url;
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(issue());
    await page.getByLabel("Expense type").fill("Parking");
    await page.getByLabel("Amount ($)").fill("20.01");
    await page
      .getByLabel("Note (optional)")
      .fill("<script>literal expense</script>");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: testInfo.outputPath("stage6-mobile-form.png"),
      fullPage: true,
    });
    let lost = false;
    await page.route(
      "**/api/technician-forms/expense/submit",
      async (route) => {
        if (!lost) {
          lost = true;
          const result = await route.fetch();
          expect(result.ok()).toBeTruthy();
          await route.abort("failed");
        } else await route.continue();
      },
    );
    await page
      .getByRole("button", { name: "Save expense", exact: true })
      .click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "Retry same submission" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Expense saved successfully.",
    );
    await page.reload();
    await expect(page.getByRole("status")).toContainText(
      "Expense saved successfully.",
    );
    let list = await (
      await request.get(`/api/technicians/${tech.id}/expenses`)
    ).json();
    expect(list.today_count).toBe(1);
    await page.goto(issue());
    await page.getByLabel("Expense type").fill("Parking");
    await page.getByLabel("Amount ($)").fill("20.01");
    await page
      .getByLabel("Note (optional)")
      .fill("<script>literal expense</script>");
    await page
      .getByRole("button", { name: "Save expense", exact: true })
      .evaluate((b: HTMLButtonElement) => {
        b.click();
        b.click();
      });
    await expect(page.getByRole("status")).toContainText(
      "Expense saved successfully.",
    );
    list = await (
      await request.get(`/api/technicians/${tech.id}/expenses`)
    ).json();
    expect(list.today_count).toBe(2);
    expect(list.today_total).toBe("40.02");
    expect(new Set(list.expenses.map((e: { id: string }) => e.id)).size).toBe(
      2,
    );
    await page.setViewportSize({ width: 1365, height: 1000 });
    await page.goto(`/technicians/${tech.id}`);
    await expect(page.getByText(/Today.*40.02/)).toBeVisible();
    await page
      .getByRole("button", { name: /Parking.*20.01/ })
      .first()
      .click();
    const detail = page.getByRole("dialog", { name: "Expense · read only" });
    await expect(
      detail.getByText("<script>literal expense</script>"),
    ).toBeVisible();
    expect(await detail.locator("script").count()).toBe(0);
    await page.screenshot({
      path: testInfo.outputPath("stage6-manager-expense.png"),
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
