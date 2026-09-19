import { test, expect, harness } from "./fixtures";
import { randomBytes } from "node:crypto";

for (const width of [320, 375, 390, 430]) {
  test(`long synthetic Work Report form stays usable at ${width}px`, async ({
    page,
  }) => {
    const job = {
      choice_id: "00000000-0000-4000-8000-000000000001",
      operational_date: "2026-09-18",
      start_time: "08:00",
      end_time: "09:00",
      sequence: 1,
      title: "<script>fictional</script>" + "LongWord".repeat(60),
      location: "<img src=x onerror=alert(1)>" + "Address".repeat(130),
      submitted: false,
    };
    await page.route("**/api/technician-forms/work-report", (route) =>
      route.fulfill({
        json: {
          status: "OPEN",
          expires_at: new Date(Date.now() + 600000).toISOString(),
          jobs: [job],
          selected: job,
          payment_choices: ["CASH", "ESTIMATE", "CANCEL", "CREDIT_CARD"],
          zero_amount_choices: ["ESTIMATE", "CANCEL"],
        },
      }),
    );
    await page.setViewportSize({ width, height: 812 });
    await page.goto(
      `/technician/work-report#${randomBytes(32).toString("base64url")}`,
    );
    const amount = page.getByLabel(/Amount of closed/);
    const payment = page.getByLabel("Type of payment");
    await payment.selectOption("CASH");
    await amount.fill("99.99");
    await payment.selectOption("ESTIMATE");
    await expect(amount).toHaveValue("0.00");
    await payment.selectOption("CASH");
    await expect(amount).toHaveValue("");
    await payment.selectOption("CANCEL");
    await payment.selectOption("CREDIT_CARD");
    await expect(amount).toHaveValue("");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    expect(
      await page.locator(".report-mobile img, .report-mobile script").count(),
    ).toBe(0);
    await page
      .getByRole("button", { name: "Submit report", exact: true })
      .scrollIntoViewIfNeeded();
    await expect(
      page.getByRole("button", { name: "Submit report", exact: true }),
    ).toBeInViewport();
  });
}

test("mobile Work Report and manager immutable receipt", async ({
  page,
  request,
  baseURL,
}, testInfo) => {
  const duplicateKeys: string[] = [];
  page.on("console", (message) => {
    if (message.text().includes("same key")) duplicateKeys.push(message.text());
  });
  harness({ action: "work_report_cleanup" });
  harness({ action: "google_reset" });
  const tech = await (
    await request.post("/api/technicians", {
      data: { first_name: "Report", last_name: "Fictional" },
    })
  ).json();
  try {
    await page.goto("/calendars");
    await page
      .getByRole("button", { name: "Connect Google Calendar", exact: true })
      .click();
    await expect(page.getByText("Connected", { exact: true })).toBeVisible();
    const grant = page.getByRole("button", {
      name: "Grant Event Access",
      exact: true,
    });
    if (await grant.isVisible()) await grant.click();
    await expect(page.getByText(/Google event access available/)).toBeVisible();
    const cal = (await (await request.get("/api/calendars")).json()).find(
      (c: { name: string }) => c.name === "GA - Atlanta",
    );
    await request.put(`/api/technicians/${tech.id}/calendar`, {
      data: { calendar_id: cal.id },
    });
    harness({
      action: "schedule_setup",
      technician_id: tech.id,
      calendar_id: cal.id,
      user_id: 891999,
      chat_id: -891999,
    });
    const { url } = harness({
      action: "work_report_issue",
      user_id: 891999,
      update_id: Date.now(),
      origin: baseURL,
    });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(url);
    await page.getByRole("button", { name: /1\. Furnace/ }).click();
    await page.getByLabel("Type of payment").selectOption("CASH");
    await page.getByLabel(/Amount of closed/).fill("850.25");
    await page.getByLabel(/Who closed/).selectOption("MYSELF");
    await page.getByLabel(/Yearly maintenance/).selectOption("yes");
    for (const platform of ["Google", "Groupon", "Facebook"])
      await page.getByLabel(`${platform} reviews`).fill("1");
    await page
      .getByLabel(/comments/)
      .fill("<script>Plain text only</script> 😀");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: testInfo.outputPath("stage5-mobile-form.png"),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Submit report", exact: true })
      .evaluate((button: HTMLButtonElement) => {
        button.click();
        button.click();
      });
    await expect(page.getByRole("status")).toContainText(
      "Report submitted successfully.",
    );
    await page.reload();
    await expect(page.getByRole("status")).toContainText(
      "Report submitted successfully.",
    );
    await page.setViewportSize({ width: 1365, height: 1000 });
    await page.goto(`/technicians/${tech.id}`);
    const saved = (
      await (
        await request.get(`/api/technicians/${tech.id}/work-reports`)
      ).json()
    ).reports[0];
    await page.getByRole("button", { name: "Daily report" }).click();
    await page.getByLabel("Business date").fill(saved.operational_date);
    await expect(
      page
        .locator(".accounting")
        .getByText("<script>Plain text only</script> 😀"),
    ).toBeVisible();
    await expect(
      page.locator(".accounting").getByText("Revision 1"),
    ).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("stage5-manager-report.png"),
      fullPage: true,
    });

    // A second job exercises forced zero, lost-response replay and an assignment
    // change after selection. All provider state belongs to this isolated fake.
    const second = harness({
      action: "work_report_issue",
      user_id: 891999,
      update_id: Date.now(),
      origin: baseURL,
    });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(second.url);
    await expect(
      page.getByRole("button", { name: /1\. Furnace/ }),
    ).toBeDisabled();
    await page.getByRole("button", { name: /2\. Dryer/ }).click();
    await page.getByLabel("Type of payment").selectOption("ESTIMATE");
    await expect(page.getByLabel(/Amount of closed/)).toHaveValue("0.00");
    await expect(page.getByLabel(/Amount of closed/)).toHaveAttribute(
      "readonly",
      "",
    );
    await page.getByLabel(/Who closed/).selectOption("CALL_CENTER");
    await page.getByLabel(/Yearly maintenance/).selectOption("no");
    for (const platform of ["Google", "Groupon", "Facebook"])
      await page.getByLabel(`${platform} reviews`).fill("0");
    expect(
      (await request.delete(`/api/technicians/${tech.id}/calendar`)).status(),
    ).toBe(204);
    const google = await (
      await request.get("/api/calendar-connections/google")
    ).json();
    expect(
      (
        await request.post("/api/calendar-connections/google/disconnect", {
          data: {
            confirmation: "DISCONNECT",
            expected_connection_id: google.id,
            expected_generation: google.generation,
          },
        })
      ).status(),
    ).toBe(204);
    let intercepted = false;
    await page.route(
      "**/api/technician-forms/work-report/submit",
      async (route) => {
        if (intercepted) return route.continue();
        intercepted = true;
        const malicious = {
          ...route.request().postDataJSON(),
          amount_closed: "999.99",
        };
        const saved = await route.fetch({ postData: malicious });
        expect(saved.status()).toBe(200);
        // The server committed, but the technician never receives its response.
        await route.abort("failed");
      },
    );
    await page
      .getByRole("button", { name: "Submit report", exact: true })
      .click();
    await expect(
      page.getByRole("alert").filter({ hasText: "retry the same submission" }),
    ).toContainText("retry the same submission");
    await page.getByRole("button", { name: "Retry same submission" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Report submitted successfully.",
    );
    await page.reload();
    await expect(page.getByRole("status")).toContainText(
      "Report submitted successfully.",
    );
    const persisted = (
      await (
        await request.get(`/api/technicians/${tech.id}/work-reports`)
      ).json()
    ).reports;
    expect(persisted).toHaveLength(2);
    expect(
      persisted.find(
        (r: { payment_method: string }) => r.payment_method === "ESTIMATE",
      ).amount_closed,
    ).toBe("0.00");
    expect(duplicateKeys).toEqual([]);
  } finally {
    harness({ action: "work_report_cleanup" });
    const latest = await (
      await request.get(`/api/technicians/${tech.id}`)
    ).json();
    await request.delete(`/api/technicians/${tech.id}`, {
      data: { confirmation: "DELETE", expected_updated_at: latest.updated_at },
    });
  }
});
