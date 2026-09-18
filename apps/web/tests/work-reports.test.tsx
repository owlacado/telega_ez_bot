import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WorkReportForm } from "@/components/work-report-form";
import { WorkReports } from "@/components/work-reports";
import { api } from "@/lib/api";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const job = {
  choice_id: "choice",
  operational_date: "2026-09-18",
  start_time: "08:00",
  end_time: "09:00",
  sequence: 1,
  title: "1. <script>Long repair</script>",
  location: "<img onerror=alert(1)>",
  submitted: false,
};
const form = {
  status: "OPEN",
  expires_at: "2026-09-18T20:15:00Z",
  jobs: [job],
  selected: null,
  payment_choices: ["CASH", "ESTIMATE", "CANCEL"],
  zero_amount_choices: ["ESTIMATE", "CANCEL"],
};
const response = (body: unknown, ok = true) => ({ ok, json: async () => body });
beforeEach(() => {
  vi.resetAllMocks();
  window.location.hash = "a".repeat(43);
});
afterEach(() => vi.unstubAllGlobals());

it("mobile picker uses opaque choices, literal provider text and forced-zero fields", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(form))
    .mockResolvedValueOnce(response({ ...form, selected: job }))
    .mockResolvedValue(response({ message: "Report submitted successfully." }));
  vi.stubGlobal("fetch", fetch);
  const { container } = render(<WorkReportForm />);
  await userEvent.click(
    await screen.findByRole("button", { name: /Long repair/ }),
  );
  expect(container.querySelector("script, img")).toBeNull();
  await userEvent.selectOptions(
    screen.getByLabelText("Type of payment"),
    "ESTIMATE",
  );
  expect(screen.getByLabelText(/Amount of closed/)).toHaveValue("0.00");
  expect(screen.getByLabelText(/Amount of closed/)).toHaveAttribute(
    "inputmode",
    "decimal",
  );
  await userEvent.selectOptions(screen.getByLabelText(/Who closed/), "MYSELF");
  await userEvent.selectOptions(
    screen.getByLabelText(/Yearly maintenance/),
    "no",
  );
  for (const label of ["Google reviews", "Groupon reviews", "Facebook reviews"])
    await userEvent.type(screen.getByLabelText(label), "0");
  await userEvent.click(screen.getByRole("button", { name: "Submit report" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Report submitted successfully.",
  );
  const body = JSON.parse(fetch.mock.calls.at(-1)?.[1].body);
  expect(body.amount_closed).toBe("0.00");
  expect(body).not.toHaveProperty("technician_id");
  expect(fetch.mock.calls[0][0]).not.toContain("a".repeat(43));
});

it("lost network response retries identical payload and suppresses double click", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response({ ...form, selected: job }))
    .mockRejectedValueOnce(new Error("Network lost"))
    .mockResolvedValue(response({}));
  vi.stubGlobal("fetch", fetch);
  const { container } = render(<WorkReportForm />);
  await screen.findByLabelText("Type of payment");
  await userEvent.selectOptions(
    screen.getByLabelText("Type of payment"),
    "CASH",
  );
  await userEvent.type(screen.getByLabelText(/Amount of closed/), "100.25");
  fireEvent.submit(container.querySelector("form")!);
  fireEvent.submit(container.querySelector("form")!);
  await userEvent.click(
    await screen.findByRole("button", { name: "Retry same submission" }),
  );
  await screen.findByRole("status");
  expect(fetch.mock.calls[1][1].body).toBe(fetch.mock.calls[2][1].body);
  expect(fetch).toHaveBeenCalledTimes(3);
});

it("empty, expired, and previously submitted form states are safe", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ ...form, jobs: [] })),
  );
  const first = render(<WorkReportForm />);
  await screen.findByText("No scheduled jobs found for today.");
  first.unmount();
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        response({ error: { message: "Form expired" } }, false),
      ),
  );
  const second = render(<WorkReportForm />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Form expired");
  second.unmount();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ ...form, status: "SUBMITTED" })),
  );
  render(<WorkReportForm />);
  await screen.findByRole("status");
  expect(screen.queryByRole("button", { name: "Submit report" })).toBeNull();
});

it("manager reads only reports for the current technician and can refresh", async () => {
  vi.mocked(api).mockResolvedValue({ reports: [], limit: 20 });
  const { rerender } = render(<WorkReports technicianId="a" />);
  await screen.findByText("No reports submitted.");
  await userEvent.click(
    screen.getByRole("button", { name: "Refresh reports" }),
  );
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
  rerender(<WorkReports technicianId="b" />);
  await waitFor(() =>
    expect(api).toHaveBeenLastCalledWith(
      "/technicians/b/work-reports",
      expect.anything(),
    ),
  );
  expect(screen.queryByText(/Net|Profit|Payout/)).toBeNull();
});
