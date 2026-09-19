import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AccountingMirror } from "@/components/accounting-mirror";
import { api } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));

const status = {
  kind: "INDIVIDUAL",
  week_start: "2026-09-14",
  week_end: "2026-09-20",
  configured: true,
  enabled: true,
  target_generation: 3,
  spreadsheet_id: "stage9Sheet_12345",
  open_url: "https://docs.google.com/spreadsheets/d/stage9Sheet_12345",
  auth_state: "READY",
  state: "SYNCED",
  pending_newer_generation: false,
  last_success_at: "2026-09-19T12:00:00Z",
  last_attempt_at: "2026-09-19T12:00:00Z",
  last_error_code: null,
  worker_state: "RUNNING",
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal(
    "confirm",
    vi.fn(() => true),
  );
});

it("shows safe status and opens only the validated constructed Sheet URL", async () => {
  vi.mocked(api).mockResolvedValue(status);
  render(<AccountingMirror technicianId="tech-a" weekStart="2026-09-14" />);
  expect(await screen.findByText("Synced")).toBeVisible();
  const link = screen.getByRole("link", { name: "Open Google Sheet" });
  expect(link).toHaveAttribute("href", status.open_url);
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
});

it("queues the exact historical week and coalesces a double click in the UI", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(api)
    .mockResolvedValueOnce(status)
    .mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
  render(<AccountingMirror technicianId="tech-a" weekStart="2026-09-14" />);
  const button = await screen.findByRole("button", { name: "Sync this week" });
  await userEvent.dblClick(button);
  expect(api).toHaveBeenCalledTimes(2);
  expect(api).toHaveBeenLastCalledWith(
    "/technicians/tech-a/accounting/mirror/action?week_start=2026-09-14",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ action: "SYNC", expected_generation: 3 }),
    }),
  );
  finish({ ...status, state: "PENDING" });
  expect(await screen.findByText("Sync queued")).toBeVisible();
});

it("uses explicit same-account OAuth upgrade for missing Sheets consent", async () => {
  vi.mocked(api)
    .mockResolvedValueOnce({
      ...status,
      configured: false,
      target_generation: null,
      auth_state: "NEEDS_PERMISSION",
      state: "NEEDS_PERMISSION",
    })
    .mockResolvedValueOnce({
      id: "connection-a",
      generation: 4,
      impact_version: "impact-a",
    })
    .mockResolvedValueOnce({ authorization_url: "/fake-google-consent" });
  render(
    <AccountingMirror
      technicianId="tech-a"
      weekStart="2026-09-07"
      allTechnicians
    />,
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Grant Sheets permission" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenLastCalledWith(
      "/calendar-connections/google/start",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          mode: "RECONNECT",
          request_sheets_access: true,
          expected_connection_id: "connection-a",
          expected_generation: 4,
          expected_impact_version: "impact-a",
        }),
      }),
    ),
  );
});
