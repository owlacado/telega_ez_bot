import { Suspense } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import TechnicianPage from "@/app/(workspace)/technicians/[id]/page";
import { api } from "@/lib/api";
import { technician } from "./fixtures";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
// Keep the real page, panels, API hook and dialogs; unrelated integrations are inert.
vi.mock("@/components/profile-panel", () => ({ ProfilePanel: () => null }));
vi.mock("@/components/accounting", () => ({ Accounting: () => null }));
vi.mock("@/components/calendar-jobs", () => ({
  TodayJobs: () => null,
  PreviewSchedule: () => null,
}));
vi.mock("@/lib/use-schedule", () => ({ useSchedule: () => ({ data: null }) }));
it("real technician route opens saved report and expense attribution/timestamps", async () => {
  const stamp = "2026-09-18T17:32:10Z";
  const common = {
    id: "saved",
    technician_id: technician.id,
    technician_name: "Name at submission",
    revision_number: 1,
    submitted_at: stamp,
  };
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/work-reports"))
      return {
        limit: 20,
        reports: [
          {
            ...common,
            operational_date: "2026-09-18",
            start_time: "08:00",
            end_time: "09:00",
            title: "Saved repair",
            location: "Fictional location",
            amount_closed: "10.00",
            payment_method: "CASH",
            closed_by: "MYSELF",
            reviews: { GOOGLE: 1, GROUPON: 0, FACEBOOK: 0 },
            yearly_maintenance_plan_provided: true,
            comments: "Saved note",
          },
        ],
      };
    if (path.endsWith("/expenses"))
      return {
        limit: 20,
        today: null,
        expenses: [
          {
            ...common,
            expense_date: "2026-09-18",
            accounting_timezone: "America/Los_Angeles",
            expense_type: "Saved supplies",
            amount: "3.00",
            note: "Expense note",
          },
        ],
      };
    return { ...technician, first_name: "Renamed", last_name: "Today" };
  });
  const params = Promise.resolve({ id: technician.id });
  await act(async () => {
    render(
      <Suspense>
        <TechnicianPage params={params} />
      </Suspense>,
    );
  });
  expect(
    await screen.findByRole("heading", { name: "Renamed Today" }),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByText("Saved submissions - details and attribution"),
  );
  fireEvent.click(await screen.findByRole("button", { name: /Saved repair/ }));
  let dialog = within(screen.getByRole("dialog"));
  expect(dialog.getByText("Name at submission")).toBeInTheDocument();
  expect(
    dialog.getByText(new Date(stamp).toLocaleString()),
  ).toBeInTheDocument();
  expect(dialog.getByText("Revision")).toBeInTheDocument();
  fireEvent.click(dialog.getByRole("button", { name: /close/i }));
  fireEvent.click(screen.getByRole("button", { name: /Saved supplies/ }));
  dialog = within(screen.getByRole("dialog"));
  expect(dialog.getByText("Name at submission")).toBeInTheDocument();
  expect(
    dialog.getByText(new Date(stamp).toLocaleString()),
  ).toBeInTheDocument();
  expect(dialog.getByText("Revision")).toBeInTheDocument();
});
