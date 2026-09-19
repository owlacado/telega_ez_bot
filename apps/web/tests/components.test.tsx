import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "@/app/(workspace)/page";
import TechniciansPage from "@/app/(workspace)/technicians/page";
import { Avatar } from "@/components/ui";
import { Sidebar } from "@/components/sidebar";
import { TechnicianCard } from "@/components/technician-card";
import { AddTechnician } from "@/components/add-technician";
import { DeleteTechnician } from "@/components/delete-technician";
import { ProfilePanel } from "@/components/profile-panel";
import { api } from "@/lib/api";
import { calendar, technician } from "./fixtures";
import { telegramState } from "./telegram-fixtures";
const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/technicians",
  useRouter: () => ({ push }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const mockedApi = vi.mocked(api);
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockedApi.mockImplementation(async (path) =>
    path === "/calendars"
      ? [calendar]
      : path.endsWith("/telegram")
        ? {
            ...telegramState,
            runtime: { ...telegramState.runtime, state: "DISABLED" },
          }
        : technician,
  );
});
afterEach(() => vi.useRealTimers());

describe("Stage 0 components", () => {
  it("collapses and persists sidebar, and keeps accessible icon labels", () => {
    const { unmount } = render(<Sidebar />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(localStorage.getItem("technician-hub:sidebar-collapsed")).toBe(
      "true",
    );
    expect(screen.getByRole("link", { name: "Technicians" })).toHaveAttribute(
      "title",
      "Technicians",
    );
    unmount();
    render(<Sidebar />);
    expect(
      screen.getByRole("button", { name: "Expand sidebar" }),
    ).toHaveAttribute("aria-expanded", "false");
  });
  it("renders an identity card with real binding states and initials", () => {
    render(<TechnicianCard technician={technician} />);
    expect(screen.getByText("DT")).toBeInTheDocument();
    expect(screen.getByText("Not assigned")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Telegram: not connected"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      `/technicians/${technician.id}`,
    );
  });
  it("creates a technician with optional calendar and opens their detail page", async () => {
    render(<AddTechnician onClose={vi.fn()} />);
    await screen.findByRole("option", { name: calendar.name });
    fireEvent.change(screen.getByLabelText("First name"), {
      target: { value: "Demo" },
    });
    fireEvent.change(screen.getByLabelText("Last name"), {
      target: { value: "Technician" },
    });
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: calendar.id },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Technician" }));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/technicians/${technician.id}`),
    );
    expect(mockedApi).toHaveBeenCalledWith(
      "/technicians",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining(calendar.id),
      }),
    );
  });
  it("keeps the add modal open on server failure", async () => {
    mockedApi.mockImplementation(async (path) => {
      if (path === "/calendars") return [];
      throw new Error("Database unavailable");
    });
    render(<AddTechnician onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("First name"), {
      target: { value: "Demo" },
    });
    fireEvent.change(screen.getByLabelText("Last name"), {
      target: { value: "Technician" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Technician" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Database unavailable",
    );
    expect(push).not.toHaveBeenCalled();
  });
  it("edits profile fields and saves calendar selection automatically", async () => {
    const onUpdate = vi.fn();
    render(<ProfilePanel technician={technician} onUpdate={onUpdate} />);
    await screen.findByRole("option", { name: calendar.name });
    fireEvent.change(screen.getByLabelText("First name"), {
      target: { value: "Updated" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await screen.findByText("Profile saved.");
    expect(mockedApi).toHaveBeenCalledWith(
      `/technicians/${technician.id}`,
      expect.objectContaining({
        method: "PATCH",
        body: expect.stringContaining('"first_name":"Updated"'),
      }),
    );
    fireEvent.change(screen.getByLabelText("Assigned calendar"), {
      target: { value: calendar.id },
    });
    await waitFor(() =>
      expect(mockedApi).toHaveBeenCalledWith(
        `/technicians/${technician.id}/calendar`,
        { method: "PUT", body: JSON.stringify({ calendar_id: calendar.id }) },
      ),
    );
    expect(
      screen.getByRole("button", { name: "Connect Telegram" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Configure GPS" }),
    ).toBeDisabled();
  });
  it("unassigns a calendar through the API", async () => {
    render(
      <ProfilePanel
        technician={{
          ...technician,
          calendar: {
            id: calendar.id,
            name: calendar.name,
            source: "LOCAL_DEMO",
            availability: "AVAILABLE",
          },
        }}
        onUpdate={vi.fn()}
      />,
    );
    await screen.findByRole("option", { name: calendar.name });
    fireEvent.change(screen.getByLabelText("Assigned calendar"), {
      target: { value: "" },
    });
    await waitFor(() =>
      expect(mockedApi).toHaveBeenCalledWith(
        `/technicians/${technician.id}/calendar`,
        { method: "DELETE" },
      ),
    );
  });
  it("requires both 10 seconds and an exact name confirmation before permanent deletion", async () => {
    vi.useFakeTimers();
    render(<DeleteTechnician technician={technician} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Deletion confirmation"), {
      target: { value: "DELETE Demo Technician" },
    });
    expect(
      screen.getByRole("button", { name: /Delete permanently/ }),
    ).toBeDisabled();
    act(() => vi.advanceTimersByTime(9000));
    expect(
      screen.getByRole("button", { name: "Delete permanently (1)" }),
    ).toBeDisabled();
    act(() => vi.advanceTimersByTime(1000));
    fireEvent.change(screen.getByLabelText("Deletion confirmation"), {
      target: { value: "DELETE Someone Else" },
    });
    expect(
      screen.getByRole("button", { name: "DELETE PERMANENTLY" }),
    ).toBeDisabled();
    expect(mockedApi).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Deletion confirmation"), {
      target: { value: "DELETE Demo Technician" },
    });
    await act(async () =>
      fireEvent.click(
        screen.getByRole("button", { name: "DELETE PERMANENTLY" }),
      ),
    );
    expect(mockedApi).toHaveBeenCalledWith(`/technicians/${technician.id}`, {
      method: "DELETE",
      body: JSON.stringify({
        confirmation: "DELETE",
        expected_updated_at: technician.updated_at,
      }),
    });
    expect(push).toHaveBeenCalledWith("/technicians");
  });
  it("resets the countdown when the delete dialog is reopened", () => {
    vi.useFakeTimers();
    const { unmount } = render(
      <DeleteTechnician technician={technician} onClose={vi.fn()} />,
    );
    act(() => vi.advanceTimersByTime(10000));
    unmount();
    render(<DeleteTechnician technician={technician} onClose={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: "Delete permanently (10)" }),
    ).toBeDisabled();
  });
});

it("resets deletion approval when the displayed record version changes", () => {
  vi.useFakeTimers();
  const props = { technician, onClose: vi.fn() };
  const { rerender } = render(<DeleteTechnician {...props} />);
  fireEvent.change(screen.getByLabelText("Deletion confirmation"), {
    target: { value: "DELETE Demo Technician" },
  });
  act(() => vi.advanceTimersByTime(10000));
  rerender(
    <DeleteTechnician
      {...props}
      technician={{ ...technician, updated_at: "2026-02-01T00:00:00Z" }}
    />,
  );
  expect(screen.getByLabelText("Deletion confirmation")).toHaveValue("");
  expect(
    screen.getByRole("button", { name: "Delete permanently (10)" }),
  ).toBeDisabled();
});
it("keeps profile inputs locked during a slow save and recovers on failure", async () => {
  let fail!: (error: Error) => void;
  mockedApi.mockImplementation((path, options) =>
    options?.method === "PATCH"
      ? new Promise((_, reject) => {
          fail = reject;
        })
      : Promise.resolve(
          path === "/calendars"
            ? []
            : path.endsWith("/telegram")
              ? telegramState
              : technician,
        ),
  );
  const update = vi.fn();
  render(<ProfilePanel technician={technician} onUpdate={update} />);
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(screen.getByLabelText("First name")).toBeDisabled();
  await act(async () => fail(new Error("Save failed")));
  expect(screen.getByRole("alert")).toHaveTextContent("Save failed");
  expect(screen.getByLabelText("First name")).toBeEnabled();
  expect(update).not.toHaveBeenCalled();
  expect(screen.queryByText("Profile saved.")).not.toBeInTheDocument();
});
it("submits deletion once, preserves confirmation on failure, and allows retry", async () => {
  vi.useFakeTimers();
  let fail!: (error: Error) => void;
  mockedApi.mockImplementationOnce(
    () =>
      new Promise((_, reject) => {
        fail = reject;
      }),
  );
  render(<DeleteTechnician technician={technician} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Deletion confirmation"), {
    target: { value: "DELETE Demo Technician" },
  });
  act(() => vi.advanceTimersByTime(10000));
  const button = screen.getByRole("button", { name: "DELETE PERMANENTLY" });
  act(() => {
    fireEvent.click(button);
    fireEvent.click(button);
  });
  expect(mockedApi).toHaveBeenCalledTimes(1);
  await act(async () => fail(new Error("Delete failed")));
  expect(screen.getByRole("alert")).toHaveTextContent("Delete failed");
  expect(push).not.toHaveBeenCalled();
  expect(button).toBeEnabled();
  await act(async () => fireEvent.click(button));
  expect(mockedApi).toHaveBeenCalledTimes(2);
  expect(push).toHaveBeenCalledWith("/technicians");
});

it("finds reversed name terms separated by extra spaces", async () => {
  mockedApi.mockResolvedValue([technician]);
  render(<TechniciansPage />);
  await screen.findByRole("link", { name: "Open Demo Technician" });
  fireEvent.change(screen.getByLabelText("Search technicians"), {
    target: { value: "  Technician   Demo  " },
  });
  expect(
    screen.getByRole("link", { name: "Open Demo Technician" }),
  ).toBeInTheDocument();
});
it("falls back to initials when a profile photo fails", () => {
  render(
    <Avatar
      firstName="Demo"
      lastName="Technician"
      url="https://example.invalid/photo.png"
    />,
  );
  fireEvent.error(screen.getByRole("img"));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByText("DT")).toBeInTheDocument();
});

it("missing accounting timezone is visible on card and dashboard before expense entry", async () => {
  const complete = {
    ...technician,
    calendar,
    accounting_timezone: null,
    integrations: {
      ...technician.integrations,
      telegram_private: "CONNECTED",
      telegram_group: "CONNECTED",
      gps_status: "CONNECTED",
    },
  } as typeof technician;
  mockedApi.mockImplementation(async (path) =>
    path === "/technicians" ? [complete] : [calendar],
  );
  const card = render(<TechnicianCard technician={complete} />);
  expect(
    screen.getByText("Accounting timezone required for expenses"),
  ).toBeInTheDocument();
  card.unmount();
  render(<Dashboard />);
  await screen.findByText("Accounting timezone required for expenses");
});

it("timezone selector preserves current value and saves an explicit choice", async () => {
  render(
    <ProfilePanel
      technician={{ ...technician, accounting_timezone: "America/New_York" }}
      onUpdate={vi.fn()}
    />,
  );
  const control = screen.getByLabelText("Accounting timezone");
  expect(control).toHaveValue("America/New_York");
  expect(screen.getByRole("option", { name: /Arizona/ })).toHaveValue(
    "America/Phoenix",
  );
  fireEvent.change(control, { target: { value: "America/Denver" } });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await screen.findByText("Profile saved.");
  expect(mockedApi).toHaveBeenCalledWith(
    `/technicians/${technician.id}`,
    expect.objectContaining({
      body: expect.stringContaining('"accounting_timezone":"America/Denver"'),
    }),
  );
});
