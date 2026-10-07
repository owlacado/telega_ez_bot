import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const job = {
  choice_id: "synthetic-choice",
  operational_date: "2030-09-18",
  start_time: "08:00",
  end_time: "09:00",
  sequence: 1,
  title: "Air conditioner service",
  location: "120 Example Street, Test City",
  submitted: false,
};
const form = {
  status: "OPEN",
  expires_at: "2030-09-18T20:15:00Z",
  jobs: [job],
  selected: job,
  payment_choices: ["CASH", "CREDIT_CARD", "ESTIMATE", "CANCEL"],
  zero_amount_choices: ["ESTIMATE", "CANCEL"],
};
const comment =
  "Replaced the air filter and tested cooling.\nNo further issues found.";
async function open(page: Page, failOnce = false) {
  const submissions: unknown[] = [];
  await page.route("**/api/**", async (route) => {
    if (route.request().url().endsWith("/submit")) {
      submissions.push(route.request().postDataJSON());
      await route.fulfill(
        failOnce && submissions.length === 1
          ? {
              status: 422,
              json: {
                error: { message: "Review the report values and try again." },
              },
            }
          : { json: { message: "Report submitted successfully." } },
      );
    } else await route.fulfill({ json: form });
  });
  await page.goto(`/technician/work-report#${"u".repeat(43)}`);
  await expect(page.getByLabel("Type of payment")).toBeVisible();
  return submissions;
}
async function fill(page: Page) {
  await page.getByLabel("Type of payment").selectOption("CASH");
  await page.getByLabel("Amount of closed project ($)").fill("125.50");
  await page.getByLabel("Who closed this project?").selectOption("MYSELF");
  for (const label of ["Google reviews", "Groupon reviews", "Facebook reviews"])
    await page.getByLabel(label).fill("0");
  await page.getByLabel("Yearly maintenance plan provided").selectOption("no");
  await page.getByLabel("Job description & comments (optional)").fill(comment);
}
async function accessible(page: Page) {
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
}
for (const width of [320, 375, 390, 430, 1440]) {
  test(`report fields and textarea at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const submissions = await open(page);
    const comments = page.getByLabel("Job description & comments (optional)");
    await expect(comments).toHaveAttribute(
      "placeholder",
      "Describe work completed, issues, parts, or notes…",
    );
    const normal = await comments.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        border: style.borderTopStyle,
        width: parseFloat(style.borderTopWidth),
        color: style.borderTopColor,
        background: style.backgroundColor,
        radius: style.borderRadius,
        padding: parseFloat(style.paddingLeft),
        height: element.getBoundingClientRect().height,
      };
    });
    expect(normal.border).toBe("solid");
    expect(normal.width).toBeGreaterThanOrEqual(1);
    expect(normal.background).toBe("rgb(252, 252, 254)");
    expect(normal.radius).toBe("9px");
    expect(normal.padding).toBeGreaterThanOrEqual(10);
    expect(normal.height).toBeGreaterThanOrEqual(120);
    await comments.hover();
    expect(
      await comments.evaluate((e) => getComputedStyle(e).borderTopColor),
    ).not.toBe(normal.color);
    await comments.focus();
    await expect(comments).toBeFocused();
    expect(
      await comments.evaluate((e) => getComputedStyle(e).outlineStyle),
    ).toBe("solid");
    await fill(page);
    await page.getByRole("heading", { name: "Submit Report" }).click();
    await expect(comments).toHaveValue(comment);
    expect(
      await comments.evaluate((e) => getComputedStyle(e).borderTopStyle),
    ).toBe("solid");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    for (const control of await page.locator("input, select, textarea").all()) {
      const box = (await control.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      if (await control.evaluate((e) => e.tagName !== "TEXTAREA"))
        expect(box.height).toBe(46);
    }
    await comments.focus();
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("button", { name: "Submit report", exact: true }),
    ).toBeFocused();
    await accessible(page);
    await page
      .getByRole("button", { name: "Submit report", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText(
      "Report submitted successfully.",
    );
    expect(submissions).toEqual([
      {
        amount_closed: "125.50",
        payment_method: "CASH",
        closed_by: "MYSELF",
        comments: comment,
        yearly_maintenance_plan_provided: false,
        reviews: { GOOGLE: 0, GROUPON: 0, FACEBOOK: 0 },
      },
    ]);
    await accessible(page);
  });
}
test("native validation, frozen retry and mobile artifacts", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const submissions = await open(page, true);
  await page.screenshot({
    path: testInfo.outputPath("report-empty.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Submit report", exact: true })
    .click();
  expect(submissions).toHaveLength(0);
  await fill(page);
  await page.getByLabel("Amount of closed project ($)").fill("1.001");
  await page
    .getByRole("button", { name: "Submit report", exact: true })
    .click();
  expect(submissions).toHaveLength(0);
  await page.getByLabel("Amount of closed project ($)").fill("125.50");
  await page.getByLabel("Google reviews").fill("101");
  await page
    .getByRole("button", { name: "Submit report", exact: true })
    .click();
  expect(submissions).toHaveLength(0);
  await page.getByLabel("Google reviews").fill("0");
  await page.getByRole("heading", { name: "Submit Report" }).click();
  await page.screenshot({
    path: testInfo.outputPath("report-filled.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Submit report", exact: true })
    .click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Review the report values",
  );
  await expect(page.locator("form")).toHaveAttribute(
    "aria-describedby",
    "report-error",
  );
  await expect(
    page.getByLabel("Job description & comments (optional)"),
  ).toBeDisabled();
  await page.screenshot({
    path: testInfo.outputPath("report-validation.png"),
    fullPage: true,
  });
  await accessible(page);
  await page.getByRole("button", { name: "Retry same submission" }).click();
  await expect(page.getByRole("status")).toBeVisible();
  expect(submissions[1]).toEqual(submissions[0]);
  await page.screenshot({
    path: testInfo.outputPath("report-success.png"),
    fullPage: true,
  });
});
