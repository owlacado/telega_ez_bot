import { test, expect, harness } from "./fixtures";
test.use({ timezoneId: "Asia/Tokyo" });
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
    await page.goto(`/technicians/${tech.id}`);
    await expect(page.getByText(/Today.s total unavailable/)).toBeVisible();
    await expect(page.getByLabel("Accounting timezone")).toHaveValue("");
    await page
      .getByLabel("Accounting timezone")
      .selectOption("America/Los_Angeles");
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(page.getByText("Profile saved.")).toBeVisible();
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
    const privateResponse = page.waitForResponse((response) =>
      response.url().endsWith("/api/technician-forms/expense"),
    );
    const formResponse = await page.goto(issue());
    // Next dev overrides the public HTML shell to no-cache; production must use no-store.
    expect(formResponse?.headers()["cache-control"]).toContain(
      process.env.E2E_BASE_URL ? "no-store" : "no-cache",
    );
    expect((await privateResponse).headers()["cache-control"]).toBe("no-store");
    expect(formResponse?.headers()["referrer-policy"]).toBe("no-referrer");
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
    expect(list.accounting_timezone).toBe("America/Los_Angeles");
    for (const expense of list.expenses) {
      const local = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Los_Angeles",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date(expense.submitted_at));
      expect(expense.expense_date).toBe(local);
    }
    expect(list.today_total).toBe("40.02");
    expect(new Set(list.expenses.map((e: { id: string }) => e.id)).size).toBe(
      2,
    );
    await page.setViewportSize({ width: 1365, height: 1000 });
    await page.goto(`/technicians/${tech.id}`);
    await expect(
      page.getByRole("region", { name: "Today accounting" }),
    ).toContainText("$40.02");
    await page.getByRole("button", { name: "Daily report" }).click();
    await expect(
      page.getByText("<script>literal expense</script>").first(),
    ).toBeVisible();
    expect(await page.locator(".accounting script").count()).toBe(0);
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
      data: {
        confirmation: "DELETE",
        expected_record_version: current.record_version,
      },
    });
  }
});
