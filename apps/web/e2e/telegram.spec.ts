import path from "node:path";
import { expect, harness, test } from "./fixtures";
test("authenticated private and group onboarding with an isolated fake transport", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const user = 7000000000 + (stamp % 100000000);
  const chat = -1007000000000 - (stamp % 100000000);
  let technicianId: string | undefined;
  try {
    await page.getByRole("link", { name: "Technicians", exact: true }).click();
    await page.getByRole("button", { name: "Add Technician" }).first().click();
    const add = page.getByRole("dialog", { name: "Add Technician" });
    await add.getByLabel("First name").fill("E2E");
    await add.getByLabel("Last name").fill(`Onboarding${stamp}`);
    await add.getByRole("button", { name: "Create Technician" }).click();
    await expect(page).toHaveURL(/\/technicians\/[0-9a-f-]{36}$/);
    technicianId = page.url().split("/").pop();
    await expect(
      page
        .getByTestId("WORK_GROUP")
        .getByRole("button", { name: "Connect Work Group" }),
    ).toBeDisabled();
    await page
      .getByRole("button", { name: "Connect Telegram", exact: true })
      .click();
    const privateDialog = page.getByRole("dialog", {
      name: "Private account connection",
    });
    const privateLink = await privateDialog
      .getByLabel("Invitation link")
      .inputValue();
    expect(await privateDialog.locator("svg title").textContent()).toBe(
      "Telegram invitation QR code",
    );
    harness({
      action: "claim",
      link: privateLink,
      user_id: user,
      update_id: stamp,
    });
    await expect(
      privateDialog.getByText("Telegram connected", { exact: true }),
    ).toBeVisible({ timeout: 10000 });
    await expect(privateDialog.getByLabel("Invitation link")).toHaveCount(0);
    await expect(
      page
        .getByTestId("PRIVATE_TELEGRAM")
        .getByText("Connected", { exact: true }),
    ).toBeVisible();
    await privateDialog.getByRole("button", { name: "Close dialog" }).click();
    await page
      .getByRole("button", { name: "Connect Work Group", exact: true })
      .click();
    const groupDialog = page.getByRole("dialog", {
      name: "Work group connection",
    });
    const groupLink = await groupDialog
      .getByLabel("Invitation link")
      .inputValue();
    harness({
      action: "claim",
      link: groupLink,
      user_id: user,
      chat_id: chat,
      update_id: stamp + 1,
    });
    await expect(
      groupDialog.getByText("Work group connected", { exact: true }),
    ).toBeVisible({ timeout: 10000 });
    await expect(groupDialog.getByLabel("Invitation link")).toHaveCount(0);
    await expect(
      page.getByTestId("WORK_GROUP").getByText("Connected", { exact: true }),
    ).toBeVisible();
    await groupDialog.getByRole("button", { name: "Close dialog" }).click();
    await page.getByRole("button", { name: "Test work group" }).click();
    await page
      .getByRole("button", { name: "Send test message", exact: true })
      .click();
    await expect(
      page.getByText("Group · Test message:", { exact: false }),
    ).toBeAttached();
    harness({ action: "deliver", user_id: user, chat_id: chat });
    await page.reload();
    await page.getByText("Recent connection activity").click();
    await expect(
      page.getByText("Group · Test message:", { exact: false }),
    ).toContainText("SENT");
    await page.evaluate(() => {
      window.scrollTo(0, 0);
      if (document.activeElement instanceof HTMLElement)
        document.activeElement.blur();
    });
    await page.screenshot({
      path: path.resolve(__dirname, "../../../.local/stage1-profile.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Manage work group" }).click();
    await groupDialog
      .getByRole("button", { name: "Disconnect work group" })
      .click();
    await page.getByRole("button", { name: "Confirm disconnect" }).click();
    await expect(
      page
        .getByTestId("WORK_GROUP")
        .getByText("Not connected", { exact: true }),
    ).toBeVisible();
    await expect(
      page
        .getByTestId("PRIVATE_TELEGRAM")
        .getByText("Connected", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();
    await page.getByRole("button", { name: "Manage private account" }).click();
    await privateDialog
      .getByRole("button", { name: "Disconnect private account" })
      .click();
    await page.getByRole("button", { name: "Confirm disconnect" }).click();
    await expect(
      page
        .getByTestId("PRIVATE_TELEGRAM")
        .getByText("Not connected", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();
    await page
      .getByRole("button", { name: "Delete Technician", exact: true })
      .click();
    const deletion = page.getByRole("dialog", {
      name: "Permanently delete technician?",
    });
    await deletion
      .getByLabel("Deletion confirmation")
      .fill(`DELETE E2E Onboarding${stamp}`);
    await expect(
      deletion.getByRole("button", { name: "DELETE PERMANENTLY", exact: true }),
    ).toBeEnabled({ timeout: 12000 });
    await deletion
      .getByRole("button", { name: "DELETE PERMANENTLY", exact: true })
      .click();
    await expect(page).toHaveURL(/\/technicians$/);
    expect(
      (await request.get(`/api/technicians/${technicianId}`)).status(),
    ).toBe(404);
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect((await request.get("/api/technicians")).status()).toBe(401);
  } finally {
    if (technicianId) {
      const current = await request.get(`/api/technicians/${technicianId}`);
      if (current.ok())
        await request.delete(`/api/technicians/${technicianId}`, {
          data: {
            confirmation: "DELETE",
            expected_updated_at: (await current.json()).updated_at,
          },
        });
    }
  }
});
