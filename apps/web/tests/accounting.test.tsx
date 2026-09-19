import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Accounting, Totals } from "@/components/accounting";
import { api, ApiError, download } from "@/lib/api";
import type { AccountingTotals } from "@hub/contracts";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
  download: vi.fn(),
}));
const totals: AccountingTotals = {
  gross_total: "1793.16",
  expense_total: "150.82",
  report_count: 11,
  expense_count: 6,
  maintenance_count: 3,
  payments: {
    CASH: "250.02",
    ZELLE: "200.02",
    CHECK: "300.03",
    CREDIT_CARD: "143.00",
    VENMO: "500.05",
    SUPER: "400.04",
    ESTIMATE: "0.00",
    CANCEL: "0.00",
  },
  reviews: { GOOGLE: 7, GROUPON: 3, FACEBOOK: 7 },
  closed_by: { MYSELF: 6, CALL_CENTER: 5 },
};
const context = {
  technician_id: "a",
  technician_name: "Synthetic Tech",
  accounting_timezone: "America/Los_Angeles",
  today: "2026-09-18",
  setup_required: false,
  calculated_at: "2026-09-18T12:00:00Z",
};
const daily = {
  ...context,
  business_date: "2026-09-18",
  previous_date: "2026-09-17",
  next_date: "2026-09-19",
  totals,
  reports: [],
  expenses: [],
};
const weekly = {
  ...context,
  week_start: "2026-09-14",
  week_end: "2026-09-20",
  previous_week: "2026-09-07",
  next_week: "2026-09-21",
  totals,
  days: Array.from({ length: 7 }, (_, i) => ({
    ...daily,
    business_date: `2026-09-${14 + i}`,
  })),
};
const current = { ...context, daily, weekly };
beforeEach(() => vi.resetAllMocks());
it("displays canonical overview without doing arithmetic or using recent lists", async () => {
  vi.mocked(api).mockResolvedValue(current);
  render(<Accounting technicianId="a" />);
  const today = await screen.findByRole("region", { name: "Today accounting" });
  expect(today).toHaveTextContent("$1793.16");
  expect(today).toHaveTextContent("$150.82");
  expect(
    screen.getByRole("region", { name: "This week accounting" }),
  ).toHaveTextContent("Facebook reviews: 7");
  expect(api).toHaveBeenCalledTimes(1);
  expect(api).toHaveBeenCalledWith(
    "/technicians/a/accounting/current",
    expect.anything(),
  );
});
it("renders server totals even when visible facts are empty", () => {
  render(<Totals value={totals} />);
  expect(screen.getByText("$1793.16")).toBeVisible();
  expect(screen.getByText("$150.82")).toBeVisible();
  expect(screen.getByText("$143.00")).toBeVisible();
  expect(screen.queryByText(/Net|Profit|Payout/)).not.toBeInTheDocument();
});
it("preserves exact server money beyond JavaScript safe integer cents", () => {
  render(
    <Totals
      value={{
        ...totals,
        gross_total: "99999999999900.00",
        expense_total: "90071992547409.91",
      }}
    />,
  );
  expect(screen.getByText("$99999999999900.00")).toBeVisible();
  expect(screen.getByText("$90071992547409.91")).toBeVisible();
  for (const label of [
    "Cash",
    "Zelle",
    "Check",
    "Credit Card / Cash App",
    "Venmo",
    "SUPER",
    "Estimate",
    "Cancel",
  ]) {
    expect(screen.getByText(label)).toBeVisible();
  }
  expect(screen.getAllByText("$0.00")).toHaveLength(2);
});
it("uses the server Today date instead of the browser date", async () => {
  vi.mocked(api).mockResolvedValue({
    ...current,
    accounting_timezone: "Asia/Tokyo",
    calculated_at: "2026-09-18T20:00:00Z",
    today: "2026-09-19",
    daily: { ...daily, business_date: "2026-09-19" },
  });
  render(<Accounting technicianId="a" />);
  expect(await screen.findByText("Today · 2026-09-19")).toBeVisible();
  expect(screen.queryByText("Today · 2026-09-18")).not.toBeInTheDocument();
});
it("handles loading then missing timezone without false UTC totals", async () => {
  vi.mocked(api).mockResolvedValue({
    ...context,
    accounting_timezone: null,
    setup_required: true,
    today: null,
    daily: null,
    weekly: null,
  });
  render(<Accounting technicianId="a" />);
  expect(
    await screen.findByText(/configure accounting timezone/),
  ).toBeVisible();
  expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
});
it("renders empty daily and uses server dates for navigation", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("current") ? current : daily,
  );
  render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Daily report" }));
  expect(
    await screen.findByText("No work reports for this date."),
  ).toBeVisible();
  expect(screen.getByText("No expenses for this date.")).toBeVisible();
  expect(screen.getByText(/Accounting timezone: America/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Previous day" }));
  await waitFor(() =>
    expect(api).toHaveBeenLastCalledWith(
      "/technicians/a/accounting/daily?date=2026-09-17",
      expect.anything(),
    ),
  );
  await userEvent.click(screen.getByRole("button", { name: "Today" }));
  await waitFor(() =>
    expect(api).toHaveBeenLastCalledWith(
      "/technicians/a/accounting/daily",
      expect.anything(),
    ),
  );
});
it("shows seven dates, mixed summary and server week navigation", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("current") ? current : weekly,
  );
  const { container } = render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Weekly report" }));
  expect(await screen.findByText(/Weekly · 2026-09-14/)).toBeVisible();
  expect(container.querySelectorAll("details")).toHaveLength(7);
  expect(screen.getByText(/Sunday · 2026-09-20/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Previous week" }));
  await waitFor(() =>
    expect(api).toHaveBeenLastCalledWith(
      "/technicians/a/accounting/weekly?week_start=2026-09-07",
      expect.anything(),
    ),
  );
});
it("renders report and expense content as plain text", async () => {
  const detail = {
    ...daily,
    reports: [
      {
        id: "r",
        sequence: 1,
        title: "Synthetic job",
        location: "<img src=x>",
        start_time: "09:00",
        end_time: "10:00",
        amount: "0.00",
        payment_method: "ESTIMATE",
        closed_by: "MYSELF",
        google_reviews: 1,
        groupon_reviews: 2,
        facebook_reviews: 3,
        maintenance: true,
        comments: "<script>report</script>",
        revision_number: 2,
      },
    ],
    expenses: [
      {
        id: "e",
        expense_type: "Gas",
        amount: "20.00",
        note: "<script>expense</script>",
        accounting_timezone: "America/Denver",
        revision_number: 2,
      },
    ],
  };
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("current") ? current : detail,
  );
  const { container } = render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Daily report" }));
  expect(await screen.findByText("<script>expense</script>")).toBeVisible();
  expect(screen.getByText("<script>report</script>")).toBeVisible();
  expect(container.querySelector("script,img")).toBeNull();
});
it("hides outdated totals after a refresh error", async () => {
  vi.mocked(api)
    .mockResolvedValueOnce(current)
    .mockRejectedValue(new Error("Unavailable"));
  render(<Accounting technicianId="a" />);
  await screen.findByRole("region", { name: "Today accounting" });
  await userEvent.click(
    screen.getByRole("button", { name: "Refresh accounting" }),
  );
  await screen.findByRole("alert");
  expect(
    screen.queryByRole("region", { name: "Today accounting" }),
  ).not.toBeInTheDocument();
});
it("ignores late technician A responses under B", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation((path) =>
    path.includes("/a/")
      ? new Promise((r) => (resolve = r))
      : Promise.resolve({
          ...current,
          technician_id: "b",
          daily: { ...daily, totals: { ...totals, gross_total: "5.00" } },
        }),
  );
  const { rerender } = render(<Accounting technicianId="a" />);
  rerender(<Accounting technicianId="b" />);
  await screen.findByText("$5.00");
  await act(async () => resolve(current));
  expect(
    within(screen.getByRole("region", { name: "Today accounting" })).getByText(
      "$5.00",
    ),
  ).toBeVisible();
});
it("ignores an older date response after a newer selection", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation((path) =>
    path.includes("current")
      ? Promise.resolve(current)
      : path.includes("date=2026-09-17")
        ? new Promise((r) => (resolve = r))
        : Promise.resolve({
            ...daily,
            business_date: path.includes("2026-09-16")
              ? "2026-09-16"
              : "2026-09-18",
          }),
  );
  render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Daily report" }));
  const input = await screen.findByLabelText("Business date");
  fireEvent.change(input, { target: { value: "2026-09-17" } });
  await waitFor(() => expect(resolve).toBeDefined());
  fireEvent.change(input, { target: { value: "2026-09-16" } });
  await screen.findByText("Daily · 2026-09-16");
  await act(async () => resolve({ ...daily, business_date: "2026-09-17" }));
  expect(screen.queryByText("Daily · 2026-09-17")).not.toBeInTheDocument();
});
it("ignores an older week response after a newer selection", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation((path) =>
    path.includes("current")
      ? Promise.resolve(current)
      : path.includes("week_start=2026-09-07")
        ? new Promise((r) => (resolve = r))
        : Promise.resolve({
            ...weekly,
            week_start: "2026-08-31",
            week_end: "2026-09-06",
          }),
  );
  render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Weekly report" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Previous week" }),
  );
  await waitFor(() => expect(resolve).toBeDefined());
  const input = screen.getByLabelText("Week starting Monday");
  fireEvent.change(input, { target: { value: "2026-08-31" } });
  await screen.findByText(/Weekly · 2026-08-31/);
  await act(async () =>
    resolve({ ...weekly, week_start: "2026-09-07", week_end: "2026-09-13" }),
  );
  expect(screen.queryByText(/Weekly · 2026-09-07/)).not.toBeInTheDocument();
});
it("downloads individual and All Tech XLSX for the exact server-selected week", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("current") ? current : weekly,
  );
  vi.mocked(download).mockResolvedValue("weekly.xlsx");
  render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Weekly report" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Download XLSX" }),
  );
  expect(download).toHaveBeenCalledWith(
    "/technicians/a/accounting/weekly.xlsx?week_start=2026-09-14",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Download All Tech XLSX" }),
  );
  expect(download).toHaveBeenLastCalledWith(
    "/accounting/weekly/all.xlsx?week_start=2026-09-14",
  );
});
it("downloads a navigated historical week instead of the current week", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("current")
      ? current
      : path.includes("2026-09-07")
        ? {
            ...weekly,
            week_start: "2026-09-07",
            week_end: "2026-09-13",
          }
        : weekly,
  );
  vi.mocked(download).mockResolvedValue("historical.xlsx");
  render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Weekly report" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Previous week" }),
  );
  await screen.findByText(/Weekly · 2026-09-07/);
  await userEvent.click(screen.getByRole("button", { name: "Download XLSX" }));
  expect(download).toHaveBeenCalledWith(
    "/technicians/a/accounting/weekly.xlsx?week_start=2026-09-07",
  );
});
it("prevents duplicate download clicks while a workbook is being prepared", async () => {
  let resolve!: (value: string) => void;
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("current") ? current : weekly,
  );
  vi.mocked(download).mockImplementation(
    () => new Promise((completion) => (resolve = completion)),
  );
  render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Weekly report" }));
  const button = await screen.findByRole("button", { name: "Download XLSX" });
  await userEvent.dblClick(button);
  expect(download).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "Preparing XLSX…" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Download All Tech XLSX" }),
  ).toBeDisabled();
  await act(async () => resolve("weekly.xlsx"));
  expect(screen.getByRole("button", { name: "Download XLSX" })).toBeEnabled();
});
it("shows a safe workbook authorization or server error", async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("current") ? current : weekly,
  );
  vi.mocked(download).mockRejectedValue(
    new ApiError("Sign in to continue.", 401),
  );
  render(<Accounting technicianId="a" />);
  await userEvent.click(screen.getByRole("button", { name: "Weekly report" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Download XLSX" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Sign in to continue.",
  );
  expect(
    screen.queryByText(/stack|filesystem|traceback/i),
  ).not.toBeInTheDocument();
});
it("keeps a pending technician download bound to its request across navigation", async () => {
  let resolveFirst!: (value: string) => void;
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("current") ? current : weekly,
  );
  vi.mocked(download)
    .mockImplementationOnce(
      () => new Promise((completion) => (resolveFirst = completion)),
    )
    .mockResolvedValueOnce("technician-b.xlsx");
  const view = render(<Accounting technicianId="technician-a" />);
  await userEvent.click(screen.getByRole("button", { name: "Weekly report" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Download XLSX" }),
  );
  expect(download).toHaveBeenCalledWith(
    "/technicians/technician-a/accounting/weekly.xlsx?week_start=2026-09-14",
  );
  view.rerender(<Accounting technicianId="technician-b" />);
  await act(async () => resolveFirst("technician-a.xlsx"));
  await userEvent.click(
    await screen.findByRole("button", { name: "Download XLSX" }),
  );
  expect(download).toHaveBeenLastCalledWith(
    "/technicians/technician-b/accounting/weekly.xlsx?week_start=2026-09-14",
  );
});
