import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const capability = "u".repeat(43);
const form = {
  status: "OPEN",
  expires_at: "2030-09-18T20:15:00Z",
  technician_name: "Alex Morgan",
  accounting_timezone: "America/Los_Angeles",
  expense_date: "2030-09-18",
  expense_id: null,
};
const receipt = "d6fd08bc-e198-4fe9-a769-0ebd225af361";
async function open(page: Page) {
  // UI-only fixture: no API, database or provider is contacted.
  let submitted = false;
  await page.route("**/api/**", async (route) => {
    const submit = route.request().url().endsWith("/submit");
    if (submit) submitted = true;
    await route.fulfill({
      json: submit
        ? { expense_id: receipt }
        : submitted
          ? {
              ...form,
              status: "SUBMITTED",
              expense_id: receipt,
              expense_date: "2030-09-19",
            }
          : form,
    });
  });
  await page.goto(`/technician/expense#${capability}`);
  await expect(page.getByLabel("Expense type", { exact: true })).toBeVisible();
}
async function filled(page: Page) {
  await page.getByLabel("Expense type", { exact: true }).fill("Parking");
  await page.getByLabel("Amount ($)", { exact: true }).fill("24.50");
  await page
    .getByLabel("Note (optional)")
    .fill("Parking near the service visit.");
}
async function accessible(page: Page) {
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
}
for (const width of [320, 375, 390, 430, 1440]) {
  test(`expense layout and keyboard at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    for (const name of ["Expense type", "Amount ($)", "Note (optional)"]) {
      const input = page.getByLabel(name, { exact: true });
      const box = (await input.boundingBox())!;
      const label = (await page
        .locator(`label[for="${await input.getAttribute("id")}"]`)
        .boundingBox())!;
      expect(label.y + label.height).toBeLessThan(box.y);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      expect(box.height).toBeLessThanOrEqual(
        name === "Note (optional)" ? 110 : 48,
      );
    }
    await page.keyboard.press("Tab");
    await expect(
      page.getByLabel("Expense type", { exact: true }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Amount ($)", { exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Note (optional)")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("button", { name: "Save expense" }),
    ).toBeFocused();
    const button = (await page
      .getByRole("button", { name: "Save expense" })
      .boundingBox())!;
    const input = (await page
      .getByLabel("Amount ($)", { exact: true })
      .boundingBox())!;
    expect(button.width).toBeCloseTo(input.width, 0);
    await accessible(page);
    await filled(page);
    await page
      .getByLabel("Expense type", { exact: true })
      .fill("P".repeat(100));
    await page.getByLabel("Amount ($)", { exact: true }).fill("9999999999.99");
    await page.getByRole("button", { name: "Save expense" }).click();
    await expect(page.getByRole("status")).toContainText("2030-09-19");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(
      page.getByRole("button", { name: "Done", exact: true }),
    ).toBeVisible();
    await accessible(page);
  });
}
test("mobile empty, filled, error and success artifacts", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await page.screenshot({
    path: testInfo.outputPath("expense-empty.png"),
    fullPage: true,
  });
  await filled(page);
  await page.screenshot({
    path: testInfo.outputPath("expense-filled.png"),
    fullPage: true,
  });
  await page.getByLabel("Amount ($)", { exact: true }).fill("24.501");
  await page.getByRole("button", { name: "Save expense" }).click();
  await expect(page.getByLabel("Amount ($)", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await page.getByLabel("Note (optional)").focus(); // dismiss native tooltip for artifact
  await page.screenshot({
    path: testInfo.outputPath("expense-validation.png"),
    fullPage: true,
  });
  await accessible(page);
  await page.getByLabel("Amount ($)", { exact: true }).fill("24.50");
  await page.getByRole("button", { name: "Save expense" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Expense saved successfully.",
  );
  await expect(page.getByRole("status")).toContainText("$24.50");
  await expect(page.getByRole("status")).toContainText("Parking");
  await expect(page.getByRole("status")).toContainText("2030-09-19");
  await expect(page.getByRole("main")).not.toContainText(receipt);
  await expect(page.getByRole("status")).not.toContainText(/queued|sent to/);
  await page.screenshot({
    path: testInfo.outputPath("expense-success.png"),
    fullPage: true,
  });
  await accessible(page);
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "Close this tab to return to Telegram.",
  );
});
