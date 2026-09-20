import { test, expect, harness } from "./fixtures";
test("durable schedule send, acknowledgement, explicit resend, and auto setting", async ({
  page,
  request,
}, testInfo) => {
  harness({ action: "google_reset" });
  const tech = await (
    await request.post("/api/technicians", {
      data: { first_name: "Schedule", last_name: "Acceptance" },
    })
  ).json();
  const user = 891234;
  const chat = -891235;
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
    if (await grant.isVisible()) {
      await grant.click();
      await expect(
        page.getByText(/Google event access available/),
      ).toBeVisible();
    }
    const calendars = await (await request.get("/api/calendars")).json();
    const cal = calendars.find(
      (c: { name: string }) => c.name === "GA - Atlanta",
    );
    expect(
      (
        await request.put(`/api/technicians/${tech.id}/calendar`, {
          data: { calendar_id: cal.id },
        })
      ).ok(),
    ).toBeTruthy();
    harness({
      action: "schedule_setup",
      technician_id: tech.id,
      calendar_id: cal.id,
      user_id: user,
      chat_id: chat,
    });
    await page.goto(`/technicians/${tech.id}`);
    await expect(
      page
        .getByRole("region", { name: "Today's Jobs" })
        .getByText("1. Furnace (old customer) didnt buy", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Preview .*Schedule/ }).click();
    const modal = page.getByRole("dialog", {
      name: "Next Work Day Schedule Preview",
    });
    const auto = modal.getByRole("checkbox", {
      name: "Automatic schedule delivery",
    });
    await expect(auto).not.toBeChecked();
    await expect(
      modal.getByRole("button", { name: "Send schedule", exact: true }),
    ).toBeEnabled();
    await modal
      .getByRole("button", { name: "Send schedule", exact: true })
      .click();
    await expect(
      modal.getByText("Schedule queued. Delivery has not yet been confirmed."),
    ).toBeVisible();
    await expect(modal.getByText(/ · Queued$/)).toBeVisible();
    harness({
      action: "schedule_deliver",
      user_id: user,
      chat_id: chat,
      acknowledge: true,
    });
    await expect(modal.getByText(/Acknowledged/)).toBeVisible({
      timeout: 15000,
    });
    await expect(
      modal.getByRole("button", { name: "Send schedule", exact: true }),
    ).toBeDisabled();
    await auto.click();
    await expect(auto).toBeChecked();
    await modal
      .getByRole("button", { name: "Resend schedule", exact: true })
      .click();
    await expect(
      modal.getByText(/Sending again can create a duplicate/),
    ).toBeVisible();
    await modal
      .getByRole("button", { name: "Confirm resend", exact: true })
      .click();
    await expect(modal.getByText(/ · Queued$/)).toBeVisible();
    harness({
      action: "schedule_deliver",
      user_id: user,
      chat_id: chat,
      ambiguous: true,
    });
    await expect(modal.getByText(/ · Outcome uncertain$/)).toBeVisible({
      timeout: 15000,
    });
    await expect(modal.getByText(/Automatic retry is stopped/)).toBeVisible();
    const entry = modal.locator(".schedule-delivery .schedule-jobs li").first();
    const widths = await entry.evaluate((el) => ({
      entry: el.clientWidth,
      content: (el.firstElementChild as HTMLElement).clientWidth,
    }));
    expect(widths.content).toBeGreaterThan(widths.entry * 0.8);
    await entry.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath("stage4-schedule-delivery.png"),
      fullPage: true,
    });
    const history = await request.get(
      `/api/technicians/${tech.id}/schedule-delivery`,
    );
    expect(history.headers()["cache-control"]).toBe("no-store");
    const text = await history.text();
    expect(text).not.toContain("encrypted_payload");
    expect(text).not.toContain("ack_token");
    expect(text).not.toContain("Synthetic Test St");
  } finally {
    const current = await request.get(`/api/technicians/${tech.id}`);
    if (current.ok())
      await request.delete(`/api/technicians/${tech.id}`, {
        data: {
          confirmation: "DELETE",
          expected_record_version: (await current.json()).record_version,
        },
      });
    harness({ action: "google_reset" });
  }
});
