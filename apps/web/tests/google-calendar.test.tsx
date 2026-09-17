import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Calendar, GoogleConnection } from "@hub/contracts";
import { GoogleCalendarConnection } from "@/components/google-calendar-connection";
import CalendarsPage from "@/app/(workspace)/calendars/page";
import { ProfilePanel } from "@/components/profile-panel";
import { telegramState } from "./telegram-fixtures";
import { TechnicianCard } from "@/components/technician-card";
import { ApiError, api } from "@/lib/api";
import { calendar, technician } from "./fixtures";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
const mocked = vi.mocked(api);
let state: GoogleConnection;
let rows: Calendar[];
beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/calendars");
  state = {
    enabled: true,
    status: "DISCONNECTED",
    calendar_count: 0,
    assignment_count: 0,
    demo_enabled: true,
  };
  rows = [{ ...calendar, source: "GOOGLE", name: "GA - Atlanta" }];
  mocked.mockImplementation(async (path) =>
    path === "/calendar-connections/google"
      ? { ...state }
      : path === "/calendars"
        ? [...rows]
        : path === "/technicians"
          ? [technician]
          : { discovered: 3 },
  );
});
function connected() {
  state = {
    ...state,
    id: "connection-id",
    generation: 1,
    status: "CONNECTED",
    account_label: "Google Calendar account",
    calendar_count: 14,
    assignment_count: 9,
  };
}
it("shows disconnected state and locks scan", async () => {
  render(<GoogleCalendarConnection onChange={vi.fn()} />);
  expect(await screen.findByText("Not connected")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Connect Google Calendar" }),
  ).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "Scan Google Calendars" }),
  ).toBeDisabled();
});
it("starts OAuth through the authenticated API and recovers from failure", async () => {
  mocked.mockImplementation(async (path) => {
    if (path.endsWith("/start")) throw new Error("Connection failed");
    return { ...state };
  });
  render(<GoogleCalendarConnection onChange={vi.fn()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Connect Google Calendar" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Connection failed",
  );
  expect(mocked).toHaveBeenCalledWith(
    "/calendar-connections/google/start",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"mode":"CONNECT"'),
    }),
  );
  expect(
    screen.getByRole("button", { name: "Connect Google Calendar" }),
  ).toBeEnabled();
});
it("scans, prevents duplicate requests, and reports success", async () => {
  connected();
  let finish!: (value: unknown) => void;
  mocked.mockImplementation((path) =>
    path.endsWith("/scan")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve({ ...state }),
  );
  const change = vi.fn();
  render(<GoogleCalendarConnection onChange={change} />);
  const scan = await screen.findByRole("button", {
    name: "Scan Google Calendars",
  });
  fireEvent.click(scan);
  fireEvent.click(scan);
  expect(screen.getByRole("button", { name: "Scanning..." })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeDisabled();
  await act(async () => finish({ discovered: 237 }));
  expect(
    await screen.findByText("Scan complete. 237 calendars discovered."),
  ).toBeVisible();
  expect(mocked.mock.calls.filter(([p]) => p.endsWith("/scan"))).toHaveLength(
    1,
  );
  expect(change).toHaveBeenCalledOnce();
});
it("shows provider failure and supports retry", async () => {
  connected();
  mocked.mockImplementation(async (path) => {
    if (path.endsWith("/scan")) throw new Error("RATE_LIMITED");
    return { ...state };
  });
  render(<GoogleCalendarConnection onChange={vi.fn()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Scan Google Calendars" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("RATE_LIMITED");
  expect(
    screen.getByRole("button", { name: "Scan Google Calendars" }),
  ).toBeEnabled();
});
it("requires reconnect for revoked authorization", async () => {
  connected();
  state.status = "REAUTH_REQUIRED";
  render(<GoogleCalendarConnection onChange={vi.fn()} />);
  expect(
    await screen.findByText("Google Calendar connection needs attention"),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Scan Google Calendars" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Reconnect Google Calendar" }),
  ).toBeEnabled();
});
it("shows replacement impact before starting OAuth", async () => {
  connected();
  render(<GoogleCalendarConnection onChange={vi.fn()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Change Google account" }),
  );
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "14 discovered calendars and 9 technician assignments",
  );
  expect(mocked.mock.calls.filter(([p]) => p.endsWith("/start"))).toHaveLength(
    0,
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("disconnect requires explicit confirmation and refreshes catalog", async () => {
  connected();
  const changed = vi.fn();
  render(<GoogleCalendarConnection onChange={changed} />);
  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
  await waitFor(() => expect(changed).toHaveBeenCalled());
  expect(mocked).toHaveBeenCalledWith(
    "/calendar-connections/google/disconnect",
    expect.objectContaining({
      body: expect.stringContaining('"confirmation":"DISCONNECT"'),
    }),
  );
});
it("filters unavailable and assigned calendars and preserves long names", async () => {
  rows.push({
    ...calendar,
    id: "unavailable",
    source: "GOOGLE",
    name: "Long " + "Calendar ".repeat(16).trim(),
    availability: "UNAVAILABLE",
    assigned_technician: { id: technician.id, name: "Demo Technician" },
  });
  render(<CalendarsPage />);
  await screen.findByText("GA - Atlanta");
  fireEvent.change(screen.getByLabelText("Filter"), {
    target: { value: "Unavailable" },
  });
  expect(screen.queryByText("GA - Atlanta")).not.toBeInTheDocument();
  expect(screen.getByTitle(rows[1].name)).toBeInTheDocument();
  expect(
    screen.getByText("Unavailable", { selector: "span.status" }),
  ).toBeVisible();
  fireEvent.change(screen.getByLabelText("Search calendars"), {
    target: { value: "missing" },
  });
  expect(screen.getByText("No calendars to show")).toBeVisible();
});
it("assigns and unassigns from the calendar table", async () => {
  render(<CalendarsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Assign" }));
  fireEvent.change(screen.getByLabelText("Assigned technician"), {
    target: { value: technician.id },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
  await waitFor(() =>
    expect(mocked).toHaveBeenCalledWith(
      `/calendars/${calendar.id}/assignment`,
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          technician_id: technician.id,
          expected_assigned_technician_id: null,
        }),
      }),
    ),
  );
});
it("confirms assigned exclusion and does not silently close on failure", async () => {
  rows[0].assigned_technician = { id: technician.id, name: "Demo Technician" };
  mocked.mockImplementation(async (path) => {
    if (path.endsWith("/exclude")) throw new Error("Assignment changed");
    return path === "/calendars"
      ? rows
      : path === "/technicians"
        ? [technician]
        : state;
  });
  render(<CalendarsPage />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Remove GA - Atlanta" }),
  );
  const modal = screen.getByRole("dialog");
  expect(modal).toHaveTextContent("will become unassigned");
  expect(modal).toHaveTextContent(
    "Nothing will be deleted from Google Calendar",
  );
  fireEvent.click(
    within(modal).getByRole("button", { name: "Remove calendar" }),
  );
  expect(await within(modal).findByRole("alert")).toHaveTextContent(
    "Assignment changed",
  );
  expect(
    within(modal).getByRole("button", { name: "Remove calendar" }),
  ).toBeEnabled();
});
it("hides exclusions until expanded and supports restore", async () => {
  rows[0].excluded_at = "2026-01-01T00:00:00Z";
  render(<CalendarsPage />);
  await screen.findByText("No calendars to show");
  expect(screen.queryByText("GA - Atlanta")).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Excluded Calendars (1)" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Restore GA - Atlanta" }));
  await waitFor(() =>
    expect(mocked).toHaveBeenCalledWith(`/calendars/${calendar.id}/restore`, {
      method: "POST",
    }),
  );
});
it("shows unavailable warning on technician cards", () => {
  render(
    <TechnicianCard
      technician={{
        ...technician,
        calendar: {
          ...calendar,
          source: "GOOGLE",
          availability: "UNAVAILABLE",
        },
      }}
    />,
  );
  expect(screen.getByText("Calendar unavailable")).toBeVisible();
});

it("unassigns an existing table assignment with its expected owner", async () => {
  rows[0].assigned_technician = { id: technician.id, name: "Demo Technician" };
  render(<CalendarsPage />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Change assignment" }),
  );
  fireEvent.change(screen.getByLabelText("Assigned technician"), {
    target: { value: "" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
  await waitFor(() =>
    expect(mocked).toHaveBeenCalledWith(
      `/calendars/${calendar.id}/assignment`,
      {
        method: "PUT",
        body: JSON.stringify({
          technician_id: null,
          expected_assigned_technician_id: technician.id,
        }),
      },
    ),
  );
});
it("shows current unavailable selection and excludes ineligible profile options", async () => {
  const assigned = {
    ...technician,
    calendar: {
      ...calendar,
      source: "GOOGLE" as const,
      availability: "UNAVAILABLE" as const,
    },
  };
  rows = [
    {
      ...calendar,
      availability: "UNAVAILABLE",
      assigned_technician: { id: technician.id, name: "Demo Technician" },
    },
    { ...calendar, id: "eligible", name: "Eligible" },
    {
      ...calendar,
      id: "excluded",
      name: "Excluded",
      excluded_at: "2026-01-01T00:00:00Z",
    },
    {
      ...calendar,
      id: "missing",
      name: "Unavailable other",
      availability: "UNAVAILABLE",
    },
  ];
  mocked.mockImplementation(async (path) =>
    path === "/calendars"
      ? rows
      : path.endsWith("/telegram")
        ? telegramState
        : assigned,
  );
  const updated = vi.fn();
  render(<ProfilePanel technician={assigned} onUpdate={updated} />);
  expect(
    await screen.findByRole("option", { name: calendar.name }),
  ).toBeDisabled();
  expect(
    screen.getByText("Calendar unavailable in connected Google account."),
  ).toBeVisible();
  expect(
    screen.queryByRole("option", { name: "Excluded" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "Unavailable other" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Assigned calendar"), {
    target: { value: "eligible" },
  });
  await waitFor(() =>
    expect(mocked).toHaveBeenCalledWith(
      `/technicians/${technician.id}/calendar`,
      { method: "PUT", body: JSON.stringify({ calendar_id: "eligible" }) },
    ),
  );
});
it("locks table actions during an assignment and recovers after failure", async () => {
  let reject!: (error: Error) => void;
  mocked.mockImplementation((path, options) =>
    options?.method === "PUT"
      ? new Promise((_, fail) => {
          reject = fail;
        })
      : Promise.resolve(
          path === "/calendars"
            ? rows
            : path === "/technicians"
              ? [technician]
              : state,
        ),
  );
  render(<CalendarsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Assign" }));
  fireEvent.change(screen.getByLabelText("Assigned technician"), {
    target: { value: technician.id },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
  expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
  expect(screen.getByLabelText("Assigned technician")).toBeDisabled();
  await act(async () => reject(new Error("Assignment conflict")));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Assignment conflict",
  );
  expect(screen.getByRole("button", { name: "Save assignment" })).toBeEnabled();
});

it("ignores a stale success marker and renders authoritative disconnected state", async () => {
  window.history.replaceState(null, "", "/calendars?google=connected");
  render(<GoogleCalendarConnection onChange={vi.fn()} />);
  expect(await screen.findByText("Not connected")).toBeVisible();
  expect(
    screen.queryByText(/Google Calendar connected\./),
  ).not.toBeInTheDocument();
  expect(window.location.search).toBe("");
});

it("does not refresh a replaced page when an old scan finishes", async () => {
  connected();
  let finish!: (value: unknown) => void;
  mocked.mockImplementation((path) =>
    path.endsWith("/scan")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve(state),
  );
  const change = vi.fn();
  const view = render(<GoogleCalendarConnection onChange={change} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Scan Google Calendars" }),
  );
  view.unmount();
  await act(async () => finish({ discovered: 10 }));
  expect(change).not.toHaveBeenCalled();
});

it("binds replacement confirmation to the displayed impact version", async () => {
  connected();
  state.impact_version = "displayed-impact";
  mocked.mockImplementation(async (path) => {
    if (path.endsWith("/start"))
      throw new ApiError("Calendar impact changed", 409);
    return { ...state };
  });
  render(<GoogleCalendarConnection onChange={vi.fn()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Change Google account" }),
  );
  state.impact_version = "new-impact";
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm account replacement" }),
  );
  await waitFor(() =>
    expect(mocked).toHaveBeenCalledWith(
      "/calendar-connections/google/start",
      expect.objectContaining({
        body: expect.stringContaining(
          '"expected_impact_version":"displayed-impact"',
        ),
      }),
    ),
  );
});

it("re-fetches profile and catalog after a rejected assignment and prevents rapid switching", async () => {
  let reject!: (error: Error) => void;
  let current = { ...technician, calendar: null };
  mocked.mockImplementation((path, options) => {
    if (options?.method === "PUT")
      return new Promise((_, fail) => {
        reject = fail;
      });
    return Promise.resolve(
      path === "/calendars"
        ? [...rows]
        : path.endsWith("/telegram")
          ? telegramState
          : current,
    );
  });
  const update = vi.fn();
  render(<ProfilePanel technician={technician} onUpdate={update} />);
  await screen.findByRole("option", { name: "GA - Atlanta" });
  const select = screen.getByLabelText("Assigned calendar");
  fireEvent.change(select, { target: { value: rows[0].id } });
  fireEvent.change(select, { target: { value: "" } });
  expect(select).toBeDisabled();
  rows = [{ ...rows[0], excluded_at: "2026-09-17T00:00:00Z" }];
  current = { ...technician, calendar: null };
  await act(async () => reject(new ApiError("Calendar excluded", 409)));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Calendar excluded",
  );
  await waitFor(() => expect(update).toHaveBeenCalledWith(current));
  await waitFor(() =>
    expect(
      screen.queryByRole("option", { name: "GA - Atlanta" }),
    ).not.toBeInTheDocument(),
  );
  expect(mocked.mock.calls.filter(([, o]) => o?.method === "PUT")).toHaveLength(
    1,
  );
});

it("reports a deleted technician during assignment recovery", async () => {
  mocked.mockImplementation(async (path, options) => {
    if (options?.method || path === `/technicians/${technician.id}`)
      throw new ApiError("Technician not found", 404);
    return path === "/calendars" ? rows : telegramState;
  });
  const missing = vi.fn();
  render(
    <ProfilePanel
      technician={technician}
      onUpdate={vi.fn()}
      onMissing={missing}
    />,
  );
  await screen.findByRole("option", { name: "GA - Atlanta" });
  fireEvent.change(screen.getByLabelText("Assigned calendar"), {
    target: { value: rows[0].id },
  });
  await waitFor(() => expect(missing).toHaveBeenCalledOnce());
});

it("renders malicious calendar metadata as plain text", async () => {
  rows[0].name =
    "<script>alert(1)</script> **[click](javascript:evil)** \u05d0 \ud83d\udd27";
  const view = render(<CalendarsPage />);
  expect(await screen.findByText(rows[0].name)).toBeVisible();
  expect(view.container.querySelector("script")).toBeNull();
  expect(view.container.querySelector('a[href^="javascript:"]')).toBeNull();
});

it("keeps OAuth controls locked after start succeeds until navigation", async () => {
  mocked.mockImplementation(async (path) =>
    path.endsWith("/start")
      ? { authorization_url: "#oauth-navigation-pending" }
      : { ...state },
  );
  render(<GoogleCalendarConnection onChange={vi.fn()} />);
  const button = await screen.findByRole("button", {
    name: "Connect Google Calendar",
  });
  fireEvent.click(button);
  await waitFor(() =>
    expect(window.location.hash).toBe("#oauth-navigation-pending"),
  );
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(
    mocked.mock.calls.filter(([path]) => path.endsWith("/start")),
  ).toHaveLength(1);
});
