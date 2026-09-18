import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import type { DeliveryRead, DispatchRead, ScheduleRead } from "@hub/contracts";
import { ScheduleDelivery } from "@/components/schedule-delivery";
import { api } from "@/lib/api";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
const schedule: ScheduleRead = {
  technician: { id: "A", first_name: "Test", last_name: "Tech" },
  state: "READY",
  display_semantics: "CALENDAR_WALL_CLOCK",
  operational_date: "2026-09-18",
  fingerprint: "a".repeat(64),
  jobs: [],
};
const data: DeliveryRead = {
  available: true,
  enabled: false,
  destination: "WORK_GROUP",
  local_time: "20:00",
  history: [],
};
const dispatch: DispatchRead = {
  id: "dispatch",
  target_date: "2026-09-18",
  fingerprint: "a".repeat(64),
  status: "SENT",
  trigger: "MANUAL",
  destination: "WORK_GROUP",
  job_count: 0,
  attempt_count: 1,
  error_code: null,
  created_at: "2026-09-17T20:00:00Z",
  sent_at: "2026-09-17T20:00:01Z",
  finished_at: "2026-09-17T20:00:01Z",
  ack_status: "PENDING",
  acknowledged_at: null,
  resend_of_id: null,
};
beforeEach(() => {
  mocked.mockReset();
});
afterEach(() => vi.useRealTimers());
it("queues with fingerprint only and suppresses duplicate clicks", async () => {
  let resolve!: (value: unknown) => void;
  let queued = false;
  mocked.mockImplementation((path, options) =>
    options?.method === "POST"
      ? new Promise((r) => {
          resolve = (value) => {
            queued = true;
            r(value);
          };
        })
      : Promise.resolve(
          queued
            ? { ...data, history: [{ ...dispatch, status: "PENDING" }] }
            : data,
        ),
  );
  render(<ScheduleDelivery id="A" schedule={schedule} refresh={vi.fn()} />);
  await screen.findByText("Work group");
  const send = screen.getByRole("button", { name: "Send schedule" });
  fireEvent.click(send);
  fireEvent.click(send);
  const calls = mocked.mock.calls.filter((c) => c[1]?.method === "POST");
  expect(calls).toHaveLength(1);
  expect(JSON.parse(calls[0][1]?.body as string)).toEqual({
    target_date: "2026-09-18",
    fingerprint: "a".repeat(64),
  });
  await act(async () => resolve({ ...dispatch, status: "PENDING" }));
  expect(
    screen.getByText("Schedule queued. Delivery has not yet been confirmed."),
  ).toBeVisible();
});
it.each(["SENT", "AMBIGUOUS", "FAILED", "CANCELLED"] as const)(
  "%s requires explicit resend confirmation",
  async (status) => {
    mocked.mockImplementation((_path, options) =>
      Promise.resolve(
        options?.method
          ? dispatch
          : { ...data, history: [{ ...dispatch, status }] },
      ),
    );
    render(<ScheduleDelivery id="A" schedule={schedule} refresh={vi.fn()} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Resend schedule" }),
    );
    expect(
      mocked.mock.calls.filter((c) => c[1]?.method === "POST"),
    ).toHaveLength(0);
    expect(
      screen.getByText(/Sending again can create a duplicate/),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Confirm resend" }));
    await waitFor(() =>
      expect(
        mocked.mock.calls.filter((c) => c[1]?.method === "POST"),
      ).toHaveLength(1),
    );
    const body = JSON.parse(
      mocked.mock.calls.find((c) => c[1]?.method === "POST")![1]
        ?.body as string,
    );
    expect(body.resend_of_id).toBe("dispatch");
    expect(body.confirm_duplicate_risk).toBe(true);
  },
);
it("default-off toggle is an explicit manager mutation", async () => {
  mocked.mockResolvedValue(data);
  render(<ScheduleDelivery id="A" schedule={schedule} refresh={vi.fn()} />);
  const checkbox = await screen.findByRole("checkbox", {
    name: "Automatic schedule delivery",
  });
  expect(checkbox).not.toBeChecked();
  fireEvent.click(checkbox);
  await waitFor(() =>
    expect(mocked.mock.calls.some((c) => c[1]?.method === "PUT")).toBe(true),
  );
  expect(mocked.mock.calls.filter((c) => c[1]?.method === "POST")).toHaveLength(
    0,
  );
});
it.each([true, false])(
  "late A history success/failure cannot overwrite B (%s)",
  async (fails) => {
    let resolve!: (value: unknown) => void;
    let reject!: (value: unknown) => void;
    mocked.mockImplementation((path) =>
      path.includes("/A/")
        ? new Promise((r, j) => {
            resolve = r;
            reject = j;
          })
        : Promise.resolve({ ...data, destination: "PRIVATE" }),
    );
    const { rerender } = render(
      <ScheduleDelivery id="A" schedule={schedule} refresh={vi.fn()} />,
    );
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    const signal = mocked.mock.calls[0][1]?.signal;
    rerender(
      <ScheduleDelivery
        id="B"
        schedule={{
          ...schedule,
          technician: { ...schedule.technician, id: "B" },
        }}
        refresh={vi.fn()}
      />,
    );
    await screen.findByText("Private Telegram");
    await act(async () => {
      if (fails) reject(Error("A failed"));
      else resolve({ ...data, history: [dispatch] });
    });
    expect(signal?.aborted).toBe(true);
    expect(screen.queryByText("Work group")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  },
);
it("pending delivery polls, and unmount stops further polling", async () => {
  vi.useFakeTimers();
  mocked.mockResolvedValue({
    ...data,
    history: [{ ...dispatch, status: "PENDING" }],
  });
  const { unmount } = render(
    <ScheduleDelivery id="A" schedule={schedule} refresh={vi.fn()} />,
  );
  await act(async () => {});
  expect(mocked).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(mocked).toHaveBeenCalledTimes(2);
  unmount();
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(mocked).toHaveBeenCalledTimes(2);
});
it("acknowledged terminal history does not poll", async () => {
  vi.useFakeTimers();
  mocked.mockResolvedValue({
    ...data,
    history: [
      {
        ...dispatch,
        ack_status: "ACKNOWLEDGED",
        acknowledged_at: "2026-09-17T20:01:00Z",
      },
    ],
  });
  render(<ScheduleDelivery id="A" schedule={schedule} refresh={vi.fn()} />);
  await act(async () => {});
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(mocked).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/Acknowledged/)).toBeVisible();
});
it("stale preview failure presents refresh guidance", async () => {
  mocked.mockImplementation((_path, options) =>
    options?.method
      ? Promise.reject(Error("SCHEDULE_CHANGED"))
      : Promise.resolve(data),
  );
  render(<ScheduleDelivery id="A" schedule={schedule} refresh={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Send schedule" }));
  await screen.findByText(
    "Schedule changed. Refresh the preview before sending.",
  );
});
