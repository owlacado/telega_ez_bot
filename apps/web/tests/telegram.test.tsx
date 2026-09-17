import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { TelegramState } from "@hub/contracts";
import { TelegramConnections } from "@/components/telegram-connections";
import { LoginForm } from "@/components/login-form";
import { api } from "@/lib/api";
import { telegramState } from "./telegram-fixtures";
const { replace, refresh } = vi.hoisted(() => ({
  replace: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, refresh }) }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const mockedApi = vi.mocked(api);
let data: TelegramState;
const candidate = {
  id: "invite-id",
  purpose: "PRIVATE_ACCOUNT" as const,
  expires_at: "2099-01-01T00:00:00Z",
  state: "AWAITING_APPROVAL",
  candidate_user_id: "12345678",
  candidate_display_name: "Test Person",
  candidate_username: null,
  candidate_chat_id: null,
  candidate_chat_title: null,
  initiator_admin: null,
  bot_admin: null,
  technician_member: null,
  verified_at: null,
  setup_error: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  data = structuredClone(telegramState);
  mockedApi.mockImplementation(async (path) =>
    path.endsWith("/invitations")
      ? {
          invitation: candidate,
          link: "https://t.me/hub_dedicated_test_bot?start=local-test",
          fallback_command: null,
        }
      : data,
  );
});
afterEach(() => vi.useRealTimers());
const renderConnections = () =>
  render(
    <TelegramConnections
      technicianId="tech-id"
      technicianName="Demo Technician"
      active
    />,
  );

it("logs in without persisting credentials", async () => {
  render(<LoginForm />);
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "manager" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "temporary-test-value" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  expect(localStorage.length).toBe(0);
});
it("generates a link, copies it and renders QR locally, then clears it on close", async () => {
  const link = "https://t.me/hub_dedicated_test_bot?start=" + "x".repeat(43);
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: copy },
  });
  mockedApi.mockImplementation(async (path) => {
    if (path.endsWith("/invitations")) {
      data.private.invitation = {
        ...candidate,
        state: "LINK_ISSUED",
        candidate_user_id: null,
      };
      data.private.state = "LINK_ISSUED";
      return {
        invitation: data.private.invitation,
        link,
        fallback_command: null,
      };
    }
    return structuredClone(data);
  });
  const { container } = renderConnections();
  fireEvent.click(
    await screen.findByRole("button", { name: "Connect Telegram" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate invitation" }));
  expect(await screen.findByLabelText("Invitation link")).toHaveValue(link);
  expect(container.querySelector("svg title")?.textContent).toBe(
    "Telegram invitation QR code",
  );
  expect(container.querySelector("img")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
  await screen.findByText("Copied");
  expect(copy).toHaveBeenCalledWith(link);
  fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(screen.queryByLabelText("Invitation link")).not.toBeInTheDocument();
  expect(localStorage.length).toBe(0);
});
it.each(["Approve account", "Reject candidate"])(
  "reviews the actual candidate through %s",
  async (label) => {
    data.private = {
      ...data.private,
      state: "AWAITING_APPROVAL",
      invitation: candidate,
    };
    renderConnections();
    fireEvent.click(
      await screen.findByRole("button", { name: "Connect Telegram" }),
    );
    expect(screen.getByText(/User ID: 12345678/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() =>
      expect(mockedApi).toHaveBeenCalledWith(
        "/technicians/tech-id/telegram/invitations/invite-id/review",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            decision: label === "Approve account" ? "APPROVE" : "REJECT",
          }),
        }),
      ),
    );
  },
);
it("keeps separate statuses and requires explicit replacement confirmation", async () => {
  data.private = {
    ...data.private,
    state: "CONNECTED",
    approved: true,
    generation: 3,
    availability: "AVAILABLE",
    telegram_id: "123",
  };
  renderConnections();
  fireEvent.click(
    await screen.findByRole("button", { name: "Manage private account" }),
  );
  expect(
    within(screen.getByTestId("PRIVATE_ACCOUNT")).getByText("Connected"),
  ).toBeVisible();
  expect(
    within(screen.getByTestId("WORK_GROUP")).getByText("Not connected"),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Replace connection" }));
  expect(
    mockedApi.mock.calls.some(([path]) => path.endsWith("/invitations")),
  ).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Confirm replacement" }));
  await waitFor(() =>
    expect(mockedApi).toHaveBeenCalledWith(
      "/technicians/tech-id/telegram/invitations",
      expect.objectContaining({
        body: JSON.stringify({
          purpose: "PRIVATE_ACCOUNT",
          replace: true,
          expected_generation: 3,
          confirmation: "REPLACE",
        }),
      }),
    ),
  );
});
it("pauses hidden polling and cancels it on unmount", async () => {
  vi.useFakeTimers();
  const view = renderConnections();
  await act(async () => {});
  const initial = mockedApi.mock.calls.length;
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
  await act(async () => vi.advanceTimersByTimeAsync(45000));
  expect(mockedApi).toHaveBeenCalledTimes(initial);
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  await act(async () => vi.advanceTimersByTimeAsync(15000));
  expect(mockedApi).toHaveBeenCalledTimes(initial + 1);
  view.unmount();
  await act(async () => vi.advanceTimersByTimeAsync(45000));
  expect(mockedApi).toHaveBeenCalledTimes(initial + 1);
});

it("submits invitation generation once during a same-tick double click", async () => {
  let reject!: (error: Error) => void;
  mockedApi.mockImplementation((path) =>
    path.endsWith("/invitations")
      ? new Promise((_, fail) => {
          reject = fail;
        })
      : Promise.resolve(data),
  );
  renderConnections();
  fireEvent.click(
    await screen.findByRole("button", { name: "Connect Telegram" }),
  );
  const button = screen.getByRole("button", { name: "Generate invitation" });
  act(() => {
    fireEvent.click(button);
    fireEvent.click(button);
  });
  expect(
    mockedApi.mock.calls.filter(([path]) => path.endsWith("/invitations")),
  ).toHaveLength(1);
  await act(async () => reject(new Error("Generation failed")));
  expect(
    within(screen.getByRole("dialog")).getByRole("alert"),
  ).toHaveTextContent("Generation failed");
  expect(button).toBeEnabled();
});
