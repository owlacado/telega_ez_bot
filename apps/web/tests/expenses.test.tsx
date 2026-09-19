import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ExpenseForm } from "@/components/expense-form";
import { Expenses } from "@/components/expenses";
import { api } from "@/lib/api";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const form = {
  status: "OPEN",
  expires_at: "2030-09-18T20:15:00Z",
  technician_name: "Expense Fictional",
  accounting_timezone: "America/Los_Angeles",
  expense_date: "2030-09-18",
  expense_id: null,
};
const expense = {
  id: "e1",
  technician_id: "a",
  technician_name: "Expense Fictional",
  expense_type: "Gas",
  amount: "20.00",
  note: "<script>literal</script>",
  expense_date: "2030-09-18",
  accounting_timezone: "America/Los_Angeles",
  revision_number: 1,
  submitted_at: "2030-09-18T20:01:00Z",
};
const listing = {
  expenses: [expense],
  limit: 20,
  today: "2030-09-18",
  accounting_timezone: "America/Los_Angeles",
  today_total: "40.00",
  today_count: 2,
};
const response = (body: unknown, ok = true) => ({ ok, json: async () => body });
beforeEach(() => {
  vi.resetAllMocks();
  window.location.hash = "a".repeat(43);
});
afterEach(() => vi.unstubAllGlobals());
it("mobile form sends only financial inputs, keeps currency string, and handles success", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(form))
    .mockResolvedValue(response({ expense_id: "saved" }));
  vi.stubGlobal("fetch", fetch);
  const { container } = render(
    <StrictMode>
      <ExpenseForm />
    </StrictMode>,
  );
  await userEvent.type(await screen.findByLabelText("Expense type"), "Parking");
  await userEvent.type(screen.getByLabelText("Amount ($)"), "20.01");
  await userEvent.type(
    screen.getByLabelText("Note (optional)"),
    "<script>literal</script>",
  );
  expect(screen.getByLabelText("Amount ($)")).toHaveAttribute(
    "inputmode",
    "decimal",
  );
  expect(
    container.querySelector('input[type="date"],input[type="file"],select'),
  ).toBeNull();
  fireEvent.submit(container.querySelector("form")!);
  fireEvent.submit(container.querySelector("form")!);
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Expense saved successfully.",
  );
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    expense_type: "Parking",
    amount: "20.01",
    note: "<script>literal</script>",
  });
  expect(fetch.mock.calls[0][1]).toMatchObject({
    cache: "no-store",
    credentials: "omit",
  });
  expect(fetch.mock.calls[0][0]).not.toContain("a".repeat(43));
});
it("lost response retries frozen payload even when fields change", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(form))
    .mockRejectedValueOnce(new Error("Lost response"))
    .mockResolvedValue(response({ expense_id: "saved" }));
  vi.stubGlobal("fetch", fetch);
  const { container } = render(<ExpenseForm />);
  await screen.findByLabelText("Expense type");
  fireEvent.change(screen.getByLabelText("Expense type"), {
    target: { value: "Gas" },
  });
  fireEvent.change(screen.getByLabelText("Amount ($)"), {
    target: { value: "20.00" },
  });
  fireEvent.submit(container.querySelector("form")!);
  await screen.findByRole("alert");
  fireEvent.change(screen.getByLabelText("Amount ($)"), {
    target: { value: "99.00" },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Retry same submission" }),
  );
  await screen.findByRole("status");
  expect(fetch.mock.calls[2][1].body).toBe(fetch.mock.calls[1][1].body);
});
it.each(["Expired form", "Stale actor", "Timezone unavailable"])(
  "displays %s safely",
  async (message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ error: { message } }, false)),
    );
    render(<ExpenseForm />);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByRole("button", { name: "Save expense" })).toBeNull();
  },
);
it("reload submitted form shows stable receipt without submission", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      response({ ...form, status: "SUBMITTED", expense_id: "saved" }),
    );
  vi.stubGlobal("fetch", fetch);
  render(<ExpenseForm />);
  expect(await screen.findByRole("status")).toHaveTextContent("saved");
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("manager list uses server total, renders literal note, and provides no edit", async () => {
  vi.mocked(api).mockResolvedValue(listing);
  const { container } = render(<Expenses technicianId="a" />);
  await userEvent.click(await screen.findByRole("button", { name: /Gas/ }));
  expect(screen.getByText(/Today.*40.00/)).toBeInTheDocument();
  expect(screen.getByText("<script>literal</script>")).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(screen.queryByRole("button", { name: /edit|delete/i })).toBeNull();
});
it("cross-technician stale response and selected expense are hidden", async () => {
  let resolveB!: (value: unknown) => void;
  vi.mocked(api)
    .mockResolvedValueOnce(listing)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveB = resolve;
        }),
    );
  const { rerender } = render(<Expenses technicianId="a" />);
  await userEvent.click(await screen.findByRole("button", { name: /Gas/ }));
  rerender(<Expenses technicianId="b" />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByText(/Gas/)).toBeNull();
  resolveB({ ...listing, expenses: [], today_count: 0, today_total: "0.00" });
  await screen.findByText("No expenses submitted.");
});
it("no timezone does not present a fabricated today total", async () => {
  vi.mocked(api).mockResolvedValue({ ...listing, today: null, expenses: [] });
  render(<Expenses technicianId="a" />);
  await waitFor(() =>
    expect(screen.getByText(/Today’s total unavailable/)).toBeInTheDocument(),
  );
});

it("opening a new capability in the same tab clears the prior receipt", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      response({ ...form, status: "SUBMITTED", expense_id: "old-receipt" }),
    )
    .mockResolvedValue(response(form));
  vi.stubGlobal("fetch", fetch);
  render(<ExpenseForm />);
  await screen.findByRole("status");
  window.location.hash = "b".repeat(43);
  fireEvent(window, new Event("hashchange"));
  await screen.findByLabelText("Expense type");
  expect(screen.queryByRole("status")).toBeNull();
  expect(fetch.mock.calls.at(-1)?.[1].headers.Authorization).toBe(
    `Bearer ${"b".repeat(43)}`,
  );
});
