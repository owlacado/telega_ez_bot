import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
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
          calendar: { id: calendar.id, name: calendar.name },
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
      body: '{"confirmation":"DELETE"}',
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
