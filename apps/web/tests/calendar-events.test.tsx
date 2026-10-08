// Calendar projection unit tests isolate the separately tested delivery panel.
vi.mock("@/components/schedule-delivery", () => ({
  ScheduleDelivery: () => null,
}));
import { StrictMode } from "react";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ScheduleRead } from "@hub/contracts";
import { api } from "@/lib/api";
import { useSchedule } from "@/lib/use-schedule";
import {
  ScheduleContent,
  TodayJobs,
  PreviewSchedule,
  previewLabel,
} from "@/components/calendar-jobs";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
const ready: ScheduleRead = {
  technician: { id: "tech", first_name: "John", last_name: "Smith" },
  calendar: { id: "cal", name: "Atlanta" },
  state: "READY",
  operational_date: "2026-09-17",
  next_schedule_date: "2026-09-18",
  timezone: "America/New_York",
  display_semantics: "CALENDAR_WALL_CLOCK",
  jobs: [],
  warnings: [],
  last_fetched_at: "2026-09-17T16:00:00Z",
};
const job = {
  provider_event_id: "event",
  calendar_id: "cal",
  summary: "1. Furnace (old customer) didnt buy",
  schedule_summary: "1. Furnace",
  start: "2026-09-17T08:00:00-04:00",
  end: "2026-09-17T09:00:00-04:00",
  is_all_day: false,
  status: "confirmed",
  display_date: "2026-09-17",
  display_start_time: "08:00",
  display_end_time: "09:00",
  job_number: 1,
  location: "Synthetic address",
};
beforeEach(() => {
  vi.resetAllMocks();
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = vi.fn();
});
function view(data: ScheduleRead | null = ready, more = {}) {
  return { data, error: false, loading: false, refresh: vi.fn(), ...more };
}
it("shows loading and disables duplicate refresh", () => {
  render(<TodayJobs resource={view(null, { loading: true })} />);
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
});
it.each([
  "NO_CALENDAR",
  "CALENDAR_UNAVAILABLE",
  "EVENT_SCOPE_REQUIRED",
  "REAUTH_REQUIRED",
  "TIMEZONE_REQUIRED",
] as const)("shows distinct %s state", (state) => {
  render(<ScheduleContent {...view({ ...ready, state })} />);
  expect(
    screen.queryByText("No scheduled jobs today."),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link")).toBeVisible();
});
it("empty success is distinct from provider failure", () => {
  const { rerender } = render(<ScheduleContent {...view()} />);
  expect(screen.getByText("No scheduled jobs today.")).toBeVisible();
  rerender(
    <ScheduleContent {...view({ ...ready, state: "PROVIDER_ERROR" })} />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Unable to refresh");
  expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
});
it("preserves calendar wall time, raw Today title and cleaned preview", () => {
  const data = { ...ready, jobs: [job] };
  const { rerender } = render(<ScheduleContent {...view(data)} />);
  expect(screen.getByText("08:00")).toBeVisible();
  expect(screen.getByText(job.summary)).toBeVisible();
  expect(screen.queryByText("05:00")).not.toBeInTheDocument();
  rerender(<ScheduleContent {...view(data)} preview />);
  expect(screen.getByText("1. Furnace")).toBeVisible();
  expect(screen.queryByText(job.summary)).not.toBeInTheDocument();
});
it("renders malicious long content as plain text", () => {
  const summary = "<script>alert(1)</script> ðŸ˜€ Ù…Ø±Ø­Ø¨Ø§ ".repeat(20);
  const { container } = render(
    <ScheduleContent
      {...view({
        ...ready,
        jobs: [{ ...job, summary, description: "<b>cancel notes</b>" }],
      })}
    />,
  );
  expect(container.querySelector("script")).toBeNull();
  expect(container.textContent).toContain(summary.trim());
});
it.each([
  ["2026-09-18", "Monday"],
  ["2026-09-19", "Monday"],
  ["2026-09-20", "Monday"],
])("preview label follows operational weekday %s", (day, label) =>
  expect(previewLabel(day, "2026-09-21")).toContain(label),
);
it("preview is read-only, loads target day and closes", async () => {
  mocked.mockResolvedValue({ ...ready, operational_date: "2026-09-18" });
  render(<PreviewSchedule id="tech" today={ready} />);
  fireEvent.click(screen.getByRole("button", { name: /Send next schedule/ }));
  await waitFor(() =>
    expect(screen.getByText("No scheduled jobs.")).toBeVisible(),
  );
  expect(screen.getByText("Friday, Sep 18")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Send schedule" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByText("No scheduled jobs.")).not.toBeInTheDocument();
});
it("Strict Mode sends one initial request and manual refresh deduplicates", async () => {
  mocked.mockResolvedValue(ready);
  const { result } = renderHook(() => useSchedule("/today"), {
    wrapper: StrictMode,
  });
  await waitFor(() => expect(result.current.data).toEqual(ready));
  expect(mocked).toHaveBeenCalledTimes(1);
  act(() => {
    result.current.refresh();
    result.current.refresh();
  });
  expect(result.current.data).toBeNull();
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
});
it.each([true, false])(
  "navigation rejects old success/failure (%s)",
  async (oldFails) => {
    let resolve!: (v: unknown) => void;
    let reject!: (v: unknown) => void;
    mocked.mockImplementationOnce(
      () =>
        new Promise((a, b) => {
          resolve = a;
          reject = b;
        }),
    );
    const { result, rerender } = renderHook(({ path }) => useSchedule(path), {
      initialProps: { path: "/A" },
    });
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    if (oldFails)
      mocked.mockResolvedValue({
        ...ready,
        technician: { ...ready.technician, id: "B" },
      });
    else mocked.mockRejectedValue(new Error("new failure"));
    rerender({ path: "/B" });
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      if (oldFails) reject(new Error("old"));
      else resolve(ready);
    });
    if (oldFails) expect(result.current.data?.technician.id).toBe("B");
    else {
      expect(result.current.error).toBe(true);
      expect(result.current.data).toBeNull();
    }
  },
);
it("refresh failure clears prior successful jobs", async () => {
  mocked
    .mockResolvedValueOnce({ ...ready, jobs: [job] })
    .mockRejectedValueOnce(new Error("offline"));
  const { result } = renderHook(() => useSchedule("/today"));
  await waitFor(() => expect(result.current.data?.jobs).toHaveLength(1));
  act(() => result.current.refresh());
  expect(result.current.data).toBeNull();
  await waitFor(() => expect(result.current.error).toBe(true));
  expect(result.current.data).toBeNull();
});
it("close and reopen ignores previous preview completion", async () => {
  let old!: (v: unknown) => void;
  mocked
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          old = r;
        }),
    )
    .mockResolvedValue({ ...ready, jobs: [job] });
  render(<PreviewSchedule id="tech" today={ready} />);
  fireEvent.click(screen.getByRole("button", { name: /Send next schedule/ }));
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(screen.getByRole("button", { name: /Send next schedule/ }));
  await waitFor(() => expect(screen.getByText("1. Furnace")).toBeVisible());
  await act(async () => old({ ...ready, state: "PROVIDER_ERROR" }));
  expect(screen.getByText("1. Furnace")).toBeVisible();
});

it.each([
  ["2026-09-17", "2026-09-18", "Friday"],
  ["2026-09-18", "2026-09-19", "Saturday"],
  ["2026-09-19", "2026-09-21", "Monday"],
  ["2026-09-20", "2026-09-21", "Monday"],
])("label uses returned target %s to %s", (today, target, name) => {
  expect(previewLabel(today, target)).toContain(name);
});

it.each(["today", "next-schedule"])(
  "%s ignores A after B success and after B failure",
  async (route) => {
    for (const latestFails of [false, true]) {
      mocked.mockReset();
      let old!: (v: unknown) => void;
      mocked.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            old = resolve;
          }),
      );
      if (latestFails) mocked.mockRejectedValueOnce(new Error("new failure"));
      else
        mocked.mockResolvedValueOnce({
          ...ready,
          jobs: [
            { ...job, summary: "B customer", schedule_summary: "B customer" },
          ],
        });
      function Reader({ id }: { id: string }) {
        const resource = useSchedule(`/technicians/${id}/calendar/${route}`);
        return (
          <ScheduleContent {...resource} preview={route === "next-schedule"} />
        );
      }
      const { rerender, unmount } = render(<Reader id="A" />);
      await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
      const signal = mocked.mock.calls[0][1]?.signal as AbortSignal;
      rerender(<Reader id="B" />);
      await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
      if (latestFails) await screen.findByRole("alert");
      else await screen.findByText("B customer");
      expect(signal.aborted).toBe(true);
      await act(async () =>
        old({
          ...ready,
          jobs: [
            { ...job, summary: "A PRIVATE", schedule_summary: "A PRIVATE" },
          ],
        }),
      );
      expect(screen.queryByText("A PRIVATE")).not.toBeInTheDocument();
      if (latestFails) expect(screen.getByRole("alert")).toBeVisible();
      else expect(screen.getByText("B customer")).toBeVisible();
      unmount();
    }
  },
);

it("triple refresh admits one request, aborts unmount and permits failure retry", async () => {
  mocked
    .mockResolvedValueOnce(ready)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(ready);
  const { result, unmount } = renderHook(() => useSchedule("/today"));
  await waitFor(() => expect(result.current.data).toEqual(ready));
  act(() => {
    result.current.refresh();
    result.current.refresh();
    result.current.refresh();
  });
  await waitFor(() => expect(result.current.error).toBe(true));
  expect(mocked).toHaveBeenCalledTimes(2);
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.data).toEqual(ready));
  const signal = mocked.mock.calls[2][1]?.signal as AbortSignal;
  unmount();
  expect(signal.aborted).toBe(true);
});

it("provider links prevent opener access and content remains literal", () => {
  const { container } = render(
    <ScheduleContent
      {...view({
        ...ready,
        jobs: [
          {
            ...job,
            summary: "<img src=x onerror=alert(1)> &amp; **bold**",
            description:
              "<script>alert(1)</script>\n[link](javascript:alert(1))",
            html_link:
              "https://calendar.google.com/calendar/event?eid=synthetic",
          },
        ],
      })}
    />,
  );
  expect(container.querySelector("img, script")).toBeNull();
  expect(container.textContent).toContain("&amp; **bold**");
  expect(screen.getByRole("link")).toHaveAttribute(
    "rel",
    "noopener noreferrer",
  );
});

it("shows the backend Sunday resolution explanation", () => {
  render(
    <ScheduleContent
      {...view({
        ...ready,
        resolution_note:
          "Sunday has no eligible jobs; the next schedule is Monday.",
      })}
      preview
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Sunday has no eligible jobs",
  );
});

it("uses the backend shared presentation without interpreting provider HTML", () => {
  const presentation =
    "Alex Test\nFriday, October 9, 2026\n08:00-09:30\n<script>notes</script>";
  const { container } = render(
    <ScheduleContent
      {...view({ ...ready, jobs: [job], presentation })}
      preview
    />,
  );
  expect(container.querySelector(".schedule-presentation")).toHaveTextContent(
    "Alex Test",
  );
  expect(container.querySelector(".schedule-presentation")?.textContent).toBe(
    presentation,
  );
  expect(container.querySelector("script")).toBeNull();
  expect(screen.queryByText(job.schedule_summary)).not.toBeInTheDocument();
});
