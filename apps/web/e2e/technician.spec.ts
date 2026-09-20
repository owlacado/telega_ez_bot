import { expect, test } from "./fixtures";
test("dashboard to pilot deactivation, with a real local calendar", async ({
  page,
  request,
}) => {
  const suffix = Date.now().toString();
  const calendarName = `DEMO - Smoke ${suffix}`;
  const createdCalendar = await request.post("/api/calendars", {
    data: { name: calendarName },
  });
  expect(createdCalendar.status()).toBe(201);
  const calendar = await createdCalendar.json();
  let technicianId: string | undefined;
  try {
    await page.route("**/*", (route) => {
      const host = new URL(route.request().url()).hostname;
      return ["127.0.0.1", "localhost"].includes(host)
        ? route.continue()
        : route.abort();
    });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "A clear view of your team." }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Technicians", exact: true }).click();
    await page.getByRole("button", { name: "Add Technician" }).first().click();
    const dialog = page.getByRole("dialog", { name: "Add Technician" });
    await dialog.getByLabel("First name").fill("Demo");
    await dialog.getByLabel("Last name").fill(`Smoke${suffix}`);
    await dialog.getByRole("button", { name: "Create Technician" }).click();
    await expect(page).toHaveURL(/\/technicians\/[0-9a-f-]{36}$/);
    technicianId = page.url().split("/").pop();
    await page.getByLabel("First name", { exact: true }).fill("Updated");
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(
      page.getByRole("heading", {
        name: `Updated Smoke${suffix}`,
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByLabel("Assigned calendar", { exact: true })
      .selectOption({ label: calendarName });
    await expect(
      page.getByLabel("Assigned calendar", { exact: true }),
    ).toHaveValue(calendar.id);
    await page.reload();
    await expect(
      page.getByLabel("Assigned calendar", { exact: true }),
    ).toHaveValue(calendar.id);
    await expect(
      page.getByRole("button", { name: /Preview .*Schedule/ }),
    ).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "Delete Technician", exact: true }),
    ).toHaveCount(0);
    await page.getByLabel("Status").selectOption("INACTIVE");
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(
      page.getByText("Profile saved.", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Status")).toHaveValue("INACTIVE");
    const saved = await request.get(`/api/technicians/${technicianId}`);
    expect(saved.status()).toBe(200);
    expect((await saved.json()).status).toBe("INACTIVE");
  } finally {
    await request.delete(`/api/calendars/${calendar.id}`, {
      data: { confirmation: "DELETE", detach_assigned: true },
    });
  }
});
