import { test, expect, harness } from "./fixtures";
test.use({ timezoneId: "Asia/Tokyo" });
test("canonical accounting daily weekly and current revision", async ({
  page,
  request,
}, testInfo) => {
  harness({ action: "expense_cleanup" });
  harness({ action: "mirror_google_setup" });
  const tech = await (
    await request.post("/api/technicians", {
      data: {
        first_name: "Accounting",
        last_name: "Fictional",
      },
    })
  ).json();
  const extraTechs: { id: string }[] = [];
  await request.patch(`/api/technicians/${tech.id}`, {
    data: { accounting_timezone: "America/Los_Angeles" },
  });
  try {
    const { today } = harness({
      action: "accounting_setup",
      technician_id: tech.id,
    });
    for (const [first_name, last_name] of [
      ["Bravo", "Fictional"],
      ["Zulu", "Fictional"],
    ]) {
      const extra = await (
        await request.post("/api/technicians", {
          data: { first_name, last_name },
        })
      ).json();
      extraTechs.push(extra);
      await request.patch(`/api/technicians/${extra.id}`, {
        data: { accounting_timezone: "America/Los_Angeles" },
      });
      harness({ action: "accounting_setup", technician_id: extra.id });
    }
    await page.goto(`/technicians/${tech.id}`);
    const region = page.getByRole("region", { name: "Today accounting" });
    await expect(region).toContainText(today);
    await expect(region).toContainText("$193.01");
    await expect(region).toContainText("$40.00");
    await page.getByRole("button", { name: "Daily report" }).click();
    await expect(
      page.getByRole("heading", { name: `Daily · ${today}` }),
    ).toBeVisible();
    await expect(page.locator(".accounting")).toContainText(
      "Facebook reviews: 2",
    );
    await expect(page.locator(".accounting")).toContainText(
      "Credit Card / Cash App",
    );
    await expect(
      page.getByText("<script>synthetic expense</script>").first(),
    ).toBeVisible();
    await page.getByRole("button", { name: "Weekly report" }).click();
    await expect(page.locator(".accounting details")).toHaveCount(7);
    await expect(page.locator(".accounting summary").first()).toContainText(
      "Monday",
    );
    await expect(page.locator(".accounting summary").last()).toContainText(
      "Sunday",
    );
    await page.getByRole("button", { name: "Previous week" }).click();
    await expect(page.locator(".accounting-metrics").first()).toContainText(
      "$55.00",
    );
    const historicalHeading = await page
      .locator(".accounting h3")
      .textContent();
    const historicalWeek = historicalHeading?.match(/\d{4}-\d{2}-\d{2}/)?.[0];
    expect(historicalWeek).toBeTruthy();
    const historicalDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download XLSX" }).click();
    const historical = await historicalDownload;
    const historicalPath = testInfo.outputPath("historical-weekly.xlsx");
    await historical.saveAs(historicalPath);
    expect(
      harness({
        action: "xlsx_inspect",
        path: historicalPath,
        expected_name: "Accounting Fictional",
        expected_total: "55.00",
        expected_week_start: historicalWeek,
      }),
    ).toMatchObject({
      name_found: true,
      week_found: true,
      total_found: true,
      formula_count: 0,
      hyperlink_count: 0,
      external_links: 0,
    });
    await page.getByRole("button", { name: "Current week" }).click();
    await expect(page.locator(".accounting-metrics").first()).toContainText(
      "$193.01",
    );
    const currentHeading = await page.locator(".accounting h3").textContent();
    const currentWeek = currentHeading?.match(/\d{4}-\d{2}-\d{2}/)?.[0];
    expect(currentWeek).toBeTruthy();
    const selectedWeek = currentWeek!;
    const individualMirror = page.getByRole("region", {
      name: "Technician Google Sheets mirror",
    });
    await individualMirror
      .getByLabel("Existing Spreadsheet ID or URL")
      .fill("stage9Individual_12345");
    await individualMirror.getByRole("button", { name: "Configure" }).click();
    await expect(individualMirror).toContainText("Ready to sync");
    await individualMirror
      .getByRole("button", { name: "Sync this week" })
      .click();
    await expect(individualMirror).toContainText("Sync queued");
    const allMirror = page.getByRole("region", {
      name: "All Tech Google Sheets mirror",
    });
    await allMirror
      .getByLabel("Existing Spreadsheet ID or URL")
      .fill("stage9AllTech_12345");
    await allMirror.getByRole("button", { name: "Configure" }).click();
    await allMirror.getByRole("button", { name: "Sync this week" }).click();
    await expect(allMirror).toContainText("Sync queued");
    const mirrorResult = harness({ action: "mirror_process" });
    expect(mirrorResult.results).toEqual([true, true]);
    expect(mirrorResult.sheets).toHaveLength(2);
    const weekEnd = new Date(`${selectedWeek}T00:00:00Z`);
    weekEnd.setUTCDate(weekEnd.getUTCDate() + 6);
    expect(
      mirrorResult.sheets.every(
        (sheet: { title: string }) =>
          sheet.title ===
          `${selectedWeek} - ${weekEnd.toISOString().slice(0, 10)}`,
      ),
    ).toBeTruthy();
    expect(JSON.stringify(mirrorResult.sheets)).toContain("$193.01");
    expect(
      mirrorResult.sheets.every(
        (sheet: { format_count: number }) => sheet.format_count > 0,
      ),
    ).toBeTruthy();
    await expect(individualMirror).toContainText("Synced", { timeout: 10_000 });
    await expect(allMirror).toContainText("Synced", { timeout: 10_000 });
    const individualDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download XLSX" }).click();
    const individual = await individualDownload;
    expect(individual.suggestedFilename()).toMatch(
      /^Accounting_Fictional_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.xlsx$/,
    );
    const individualPath = testInfo.outputPath("individual-weekly.xlsx");
    await individual.saveAs(individualPath);
    expect(
      harness({
        action: "xlsx_inspect",
        path: individualPath,
        expected_name: "Accounting Fictional",
        expected_total: "193.01",
        expected_week_start: currentWeek,
        expected_expense: "40.00",
        expected_cash: "100.01",
        expected_google: 3,
      }),
    ).toMatchObject({
      sheet: "Weekly Report",
      name_found: true,
      total_found: true,
      week_found: true,
      expense_total_found: true,
      cash_found: true,
      google_reviews_found: true,
      representative_styles: true,
      formula_count: 0,
      hyperlink_count: 0,
      external_links: 0,
    });
    const allTechDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download All Tech XLSX" }).click();
    const allTech = await allTechDownload;
    expect(allTech.suggestedFilename()).toMatch(
      /^All_Tech_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.xlsx$/,
    );
    const allTechPath = testInfo.outputPath("all-tech-weekly.xlsx");
    await allTech.saveAs(allTechPath);
    expect(
      harness({
        action: "xlsx_inspect",
        path: allTechPath,
        expected_name: "Accounting Fictional",
        expected_names: [
          "Accounting Fictional",
          "Bravo Fictional",
          "Zulu Fictional",
        ],
        expected_total: "193.01",
        expected_week_start: currentWeek,
        expected_expense: "40.00",
        expected_cash: "100.01",
        expected_google: 3,
      }),
    ).toMatchObject({
      sheet: "All Tech Weekly Report",
      name_found: true,
      expected_names_found: true,
      expected_band_titles: [
        "Accounting Fictional",
        "Bravo Fictional",
        "Zulu Fictional",
      ],
      total_found: true,
      total_match_count: 3,
      week_found: true,
      expense_total_found: true,
      cash_found: true,
      google_reviews_found: true,
      representative_styles: true,
      block_style_parity: true,
      formula_count: 0,
      hyperlink_count: 0,
      external_links: 0,
    });
    harness({ action: "accounting_correct", technician_id: tech.id });
    await page.getByRole("button", { name: "Refresh accounting" }).click();
    await expect(page.locator(".accounting-metrics").first()).toContainText(
      "$268.01",
    );
    await page.getByRole("button", { name: "Overview", exact: true }).click();
    await expect(region).toContainText("$268.01");
    await page.screenshot({
      path: testInfo.outputPath("stage7-accounting-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 375, height: 812 });
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      )
      .toBeTruthy();
    await page.screenshot({
      path: testInfo.outputPath("stage7-accounting-mobile.png"),
      fullPage: true,
    });
  } finally {
    harness({ action: "mirror_cleanup" });
    harness({ action: "expense_cleanup" });
    for (const currentTech of [tech, ...extraTechs]) {
      const currentResponse = await request.get(
        `/api/technicians/${currentTech.id}`,
      );
      if (currentResponse.ok()) {
        const current = await currentResponse.json();
        await request.delete(`/api/technicians/${currentTech.id}`, {
          data: {
            confirmation: "DELETE",
            expected_updated_at: current.updated_at,
          },
        });
      }
    }
  }
});
