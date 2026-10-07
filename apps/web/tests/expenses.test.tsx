import { StrictMode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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
  expect(fetch).toHaveBeenCalledTimes(3);
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

it("a late A request cannot replace B financial facts", async () => {
  let resolveA!: (value: unknown) => void;
  vi.mocked(api)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveA = resolve;
        }),
    )
    .mockResolvedValueOnce({
      ...listing,
      expenses: [
        { ...expense, id: "b1", technician_id: "b", expense_type: "B only" },
      ],
      today_total: "9.99",
    });
  const { rerender } = render(<Expenses technicianId="a" />);
  rerender(<Expenses technicianId="b" />);
  await screen.findByRole("button", { name: /B only/ });
  await act(async () => resolveA(listing));
  expect(screen.queryByRole("button", { name: /Gas/ })).toBeNull();
  expect(screen.getByText(/Today.*9.99/)).toBeInTheDocument();
  expect(screen.queryByText(/40.00/)).toBeNull();
});

it("financial facts never claim net, profit or payout", async () => {
  vi.mocked(api).mockResolvedValue(listing);
  const { container } = render(<Expenses technicianId="a" />);
  await screen.findByText(/Today/);
  expect(container.textContent).not.toMatch(/net|profit|payout/i);
});

it("associates server field errors without changing labels or retry payload", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(response(form))
      .mockResolvedValue(
        response(
          {
            error: {
              details: [
                {
                  field: "body.expense_type",
                  message: "Use plain text without markup.",
                },
              ],
            },
          },
          false,
        ),
      ),
  );
  const { container } = render(<ExpenseForm />);
  await userEvent.type(
    await screen.findByLabelText("Expense type"),
    "<Parking>",
  );
  await userEvent.type(screen.getByLabelText("Amount ($)"), "24.50");
  fireEvent.submit(container.querySelector("form")!);
  await screen.findByRole("alert");
  const field = screen.getByLabelText("Expense type");
  expect(field).toHaveAttribute("aria-invalid", "true");
  expect(field).toHaveAccessibleDescription("Use plain text without markup.");
  expect(screen.getByLabelText("Amount ($)")).not.toHaveAttribute(
    "aria-invalid",
  );
  await userEvent.clear(field);
  expect(field).not.toHaveAttribute("aria-invalid");
});
it("does not expose internal receipt or invent a group-delivery status", async () => {
  const id = "d6fd08bc-e198-4fe9-a769-0ebd225af361";
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        response({ ...form, status: "SUBMITTED", expense_id: id }),
      ),
  );
  const { container } = render(<ExpenseForm />);
  await screen.findByRole("status");
  expect(container).not.toHaveTextContent(id);
  expect(screen.getByRole("status")).not.toHaveTextContent(
    /queued|sent to|delivered/i,
  );
  await userEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(screen.getByRole("status")).toHaveTextContent(
    "Close this tab to return to Telegram.",
  );
});

it("summarizes the accepted frozen payload and persisted date across midnight", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(form))
    .mockRejectedValueOnce(new Error("Lost response"))
    .mockResolvedValueOnce(response({ expense_id: "saved" }))
    .mockResolvedValue(
      response({
        ...form,
        status: "SUBMITTED",
        expense_id: "saved",
        expense_date: "2030-09-19",
      }),
    );
  vi.stubGlobal("fetch", fetch);
  const { container } = render(<ExpenseForm />);
  await userEvent.type(
    await screen.findByLabelText("Expense type"),
    " Parking ",
  );
  await userEvent.type(screen.getByLabelText("Amount ($)"), "00024.5");
  fireEvent.submit(container.querySelector("form")!);
  await screen.findByRole("alert");
  fireEvent.change(screen.getByLabelText("Amount ($)"), {
    target: { value: "99.00" },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Retry same submission" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("2030-09-19"),
  );
  expect(screen.getByRole("status")).toHaveTextContent("$24.50");
  expect(screen.getByRole("status")).toHaveTextContent("Parking");
  expect(screen.getByRole("status")).not.toHaveTextContent("99.00");
  expect(screen.getByRole("status")).not.toHaveTextContent("2030-09-18");
  expect(fetch.mock.calls[3][0]).toBe("/api/technician-forms/expense");
  expect(JSON.parse(fetch.mock.calls[3][1].body)).toEqual({});
});
it("failed saved-date read never retries a successful financial submission", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(form))
    .mockResolvedValueOnce(response({ expense_id: "saved" }))
    .mockRejectedValue(new Error("Expired form"));
  vi.stubGlobal("fetch", fetch);
  const { container } = render(<ExpenseForm />);
  await userEvent.type(await screen.findByLabelText("Expense type"), "Gas");
  await userEvent.type(screen.getByLabelText("Amount ($)"), "10");
  fireEvent.submit(container.querySelector("form")!);
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("Unavailable"),
  );
  expect(screen.getByRole("status")).toHaveTextContent("$10.00");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Retry same submission" }),
  ).toBeNull();
  expect(
    fetch.mock.calls.filter(([url]) => url.endsWith("/submit")),
  ).toHaveLength(1);
});
it("late saved-date response cannot replace a new capability's form", async () => {
  let resolveDate!: (value: unknown) => void;
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(form))
    .mockResolvedValueOnce(response({ expense_id: "old" }))
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveDate = resolve;
        }),
    )
    .mockResolvedValue(
      response({ ...form, technician_name: "New Technician" }),
    );
  vi.stubGlobal("fetch", fetch);
  const { container } = render(<ExpenseForm />);
  await userEvent.type(await screen.findByLabelText("Expense type"), "Gas");
  await userEvent.type(screen.getByLabelText("Amount ($)"), "10");
  fireEvent.submit(container.querySelector("form")!);
  await screen.findByRole("status");
  window.location.hash = "b".repeat(43);
  fireEvent(window, new Event("hashchange"));
  await screen.findByText("New Technician");
  await act(async () =>
    resolveDate(
      response({
        ...form,
        status: "SUBMITTED",
        expense_id: "old",
        expense_date: "2030-09-19",
      }),
    ),
  );
  expect(screen.getByText("New Technician")).toBeInTheDocument();
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.queryByText("$10.00")).toBeNull();
});
