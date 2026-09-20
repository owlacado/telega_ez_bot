import path from "node:path";
import { spawnSync } from "node:child_process";
import { test, expect } from "./fixtures";

// Exercise the real Python provider-normalization/projection code, then render its
// response in Chromium. No provider injection endpoint or live Google call exists.
function projected(zone: string, offset: string) {
  const root = path.resolve(__dirname, "../../..");
  const python = path.join(
    root,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const script = `import json,sys
from datetime import date
from uuid import UUID
from hub.calendar_events.normalization import normalize_event
from hub.calendar_events.domain import build_technician_schedule
zone,offset=sys.argv[1:]
raw={'id':'wall-clock','summary':'1. Synthetic repair','start':{'dateTime':'2026-09-17T08:00:00'+offset},'end':{'dateTime':'2026-09-17T09:00:00'+offset}}
event=normalize_event(raw,zone)
jobs,warnings=build_technician_schedule(UUID(int=1),date(2026,9,17),zone,[event])
print(json.dumps([job.model_dump(mode='json') for job in jobs]))`;
  const result = spawnSync(python, ["-c", script, zone, offset], {
    cwd: root,
    encoding: "utf8",
  });
  if (result.status !== 0) throw new Error("Synthetic projection failed");
  return JSON.parse(result.stdout);
}

for (const [zone, browserZone, offset] of [
  ["America/New_York", "America/Los_Angeles", "-04:00"],
  ["America/Denver", "America/New_York", "-06:00"],
  ["America/Los_Angeles", "UTC", "-07:00"],
]) {
  test.describe(`${zone} calendar in ${browserZone} browser`, () => {
    test.use({ timezoneId: browserZone });
    test("renders provider 08:00 unchanged in Today and Preview", async ({
      page,
      request,
    }) => {
      const tech = await (
        await request.post("/api/technicians", {
          data: { first_name: "Clock", last_name: "Audit" },
        })
      ).json();
      const value = {
        technician: { id: tech.id, first_name: "Clock", last_name: "Audit" },
        state: "READY",
        calendar: {
          id: "00000000-0000-0000-0000-000000000001",
          name: "Synthetic calendar",
        },
        operational_date: "2026-09-17",
        next_schedule_date: "2026-09-18",
        timezone: zone,
        display_semantics: "CALENDAR_WALL_CLOCK",
        jobs: projected(zone, offset),
        warnings: [],
      };
      await page.route(`**/api/technicians/${tech.id}/calendar/*`, (route) =>
        route.fulfill({ json: value }),
      );
      try {
        await page.goto(`/technicians/${tech.id}`);
        await expect(
          page.getByRole("region", { name: "Today's Jobs" }).locator("time"),
        ).toHaveText("08:00");
        await page.getByRole("button", { name: /Preview Friday/ }).click();
        await expect(page.getByRole("dialog").locator("time")).toHaveText(
          "08:00",
        );
      } finally {
        const current = await request.get(`/api/technicians/${tech.id}`);
        await request.delete(`/api/technicians/${tech.id}`, {
          data: {
            confirmation: "DELETE",
            expected_record_version: (await current.json()).record_version,
          },
        });
      }
    });
  });
}

test("large bounded schedule renders literal text without horizontal overflow", async ({
  page,
  request,
}) => {
  const tech = await (
    await request.post("/api/technicians", {
      data: { first_name: "Large", last_name: "Audit" },
    })
  ).json();
  const base = projected("America/New_York", "-04:00")[0];
  const jobs = Array.from({ length: 500 }, (_, i) => ({
    ...base,
    provider_event_id: `bounded-${i}`,
    summary: "<img onerror=alert(1)> &amp; **plain** " + "x".repeat(450),
    description: "note\n".repeat(800),
    location: "x".repeat(1000),
  }));
  await page.route(`**/api/technicians/${tech.id}/calendar/today`, (route) =>
    route.fulfill({
      json: {
        technician: { id: tech.id, first_name: "Large", last_name: "Audit" },
        state: "READY",
        calendar: { id: base.calendar_id, name: "Synthetic" },
        operational_date: "2026-09-17",
        timezone: "America/New_York",
        jobs,
        warnings: [],
      },
    }),
  );
  try {
    await page.goto(`/technicians/${tech.id}`);
    const region = page.getByRole("region", { name: "Today's Jobs" });
    await expect(region.locator("li")).toHaveCount(500);
    await expect(region.locator("img, script")).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await expect(region.locator("li").first()).toContainText("&amp; **plain**");
  } finally {
    const current = await request.get(`/api/technicians/${tech.id}`);
    await request.delete(`/api/technicians/${tech.id}`, {
      data: {
        confirmation: "DELETE",
        expected_record_version: (await current.json()).record_version,
      },
    });
  }
});
