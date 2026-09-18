import { test, expect, harness } from "./fixtures";

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
    await expect(page.getByText("1 reports shown")).toBeVisible();
    await page.getByRole("button", { name: /Cash · \$850.25/ }).click();
    const detail = page.getByRole("dialog", {
      name: "Work report · read only",
    });
    await expect(
      detail.getByText("<script>Plain text only</script> 😀"),
    ).toBeVisible();
    await expect(detail.getByText("Revision", { exact: true })).toBeVisible();
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
