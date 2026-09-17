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
    await expect(
      page.getByText("Google Calendar connected. You can scan calendars now."),
    ).toBeVisible();
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
    await expect(
      page.getByText("Google Calendar connected. You can scan calendars now."),
    ).toBeVisible();
    await expect(savannah).toContainText("Available");
  } finally {
    const current = await request.get(`/api/technicians/${technician.id}`);
    if (current.ok())
      await request.delete(`/api/technicians/${technician.id}`, {
        data: {
          confirmation: "DELETE",
          expected_updated_at: (await current.json()).updated_at,
        },
      });
    harness({ action: "google_reset" });
  }
});
