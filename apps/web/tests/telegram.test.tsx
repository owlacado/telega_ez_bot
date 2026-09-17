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
  automatic: false,
  id: "invite-id",
  purpose: "PRIVATE_TELEGRAM" as const,
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
    within(screen.getByTestId("PRIVATE_TELEGRAM")).getByText("Connected"),
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
          purpose: "PRIVATE_TELEGRAM",
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

function automaticInvitation(
  purpose: "PRIVATE_TELEGRAM" | "WORK_GROUP" = "PRIVATE_TELEGRAM",
  seconds = 900,
) {
  return {
    ...candidate,
    automatic: true,
    purpose,
    state: "PENDING",
    candidate_user_id: null,
    expires_at: new Date(Date.now() + seconds * 1000).toISOString(),
  };
}
function automaticApi(
  purpose: "PRIVATE_TELEGRAM" | "WORK_GROUP" = "PRIVATE_TELEGRAM",
  seconds = 900,
) {
  const key = purpose === "PRIVATE_TELEGRAM" ? "private" : "group";
  const invitation = automaticInvitation(purpose, seconds);
  const link =
    "https://t.me/hub_dedicated_test_bot?" +
    (key === "private" ? "start" : "startgroup") +
    "=" +
    "q".repeat(43);
  mockedApi.mockImplementation(async (path) => {
    if (path.endsWith("/invitations")) {
      data[key] = { ...data[key], state: "PENDING", invitation };
      return {
        invitation,
        link,
        fallback_command:
          key === "group"
            ? "/start@hub_dedicated_test_bot " + "q".repeat(43)
            : null,
      };
    }
    if (path.endsWith("/revoke"))
      data[key] = {
        ...data[key],
        state: "NOT_CONNECTED",
        invitation: { ...invitation, state: "REVOKED" },
      };
    if (path.endsWith("/disconnect"))
      data[key] = {
        ...data[key],
        state: "NOT_CONNECTED",
        approved: false,
        telegram_id: null,
      };
    return structuredClone(data);
  });
  return { key, invitation, link };
}
it("connect immediately creates one invitation, countdown and safe copy/open actions", async () => {
  vi.useFakeTimers();
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: copy },
  });
  const { link } = automaticApi();
  renderConnections();
  await act(async () => {});
  const button = screen.getByRole("button", { name: "Connect Telegram" });
  await act(async () => {
    fireEvent.click(button);
    fireEvent.click(button);
  });
  expect(
    mockedApi.mock.calls.filter(([path]) => path.endsWith("/invitations")),
  ).toHaveLength(1);
  expect(screen.getByLabelText("Invitation link")).toHaveValue(link);
  expect(screen.getByRole("link", { name: "Open Telegram" })).toHaveAttribute(
    "rel",
    "noopener noreferrer",
  );
  expect(screen.getByText(/Invitation expires in 15:00/)).toBeVisible();
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByText(/Invitation expires in 14:58/)).toBeVisible();
  await act(async () =>
    fireEvent.click(
      screen.getByRole("button", { name: "Copy setup instructions" }),
    ),
  );
  expect(copy).toHaveBeenCalledWith(expect.stringContaining(link));
  expect(copy).toHaveBeenCalledWith(expect.stringContaining("Demo Technician"));
});
it.each(["CONNECTED", "EXPIRED", "REVOKED", "ERROR"])(
  "polls then stops for %s and clears credential",
  async (terminal) => {
    vi.useFakeTimers();
    const { invitation } = automaticApi();
    renderConnections();
    await act(async () => {});
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: "Connect Telegram" })),
    );
    data.private = {
      ...data.private,
      state: terminal,
      approved: terminal === "CONNECTED",
      availability: "AVAILABLE",
      username: "demo_tech",
      telegram_id: terminal === "CONNECTED" ? "123" : null,
      invitation:
        terminal === "CONNECTED" ? null : { ...invitation, state: terminal },
    };
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(screen.queryByLabelText("Invitation link")).not.toBeInTheDocument();
    if (terminal === "CONNECTED") {
      expect(screen.getByText("Telegram connected")).toBeVisible();
      expect(
        within(screen.getByTestId("PRIVATE_TELEGRAM")).getByText("@demo_tech"),
      ).toBeVisible();
      expect(
        within(screen.getByTestId("PRIVATE_TELEGRAM")).getByText(/Telegram ID/),
      ).not.toBeVisible();
    }
    const count = mockedApi.mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(mockedApi.mock.calls.length).toBe(count);
  },
);
it("local expiry hides the link while the server remains authoritative", async () => {
  vi.useFakeTimers();
  automaticApi("PRIVATE_TELEGRAM", 2);
  renderConnections();
  await act(async () => {});
  await act(async () =>
    fireEvent.click(screen.getByRole("button", { name: "Connect Telegram" })),
  );
  await act(async () => vi.advanceTimersByTimeAsync(2100));
  expect(screen.queryByLabelText("Invitation link")).not.toBeInTheDocument();
  expect(screen.getByText(/Invitation expired/)).toBeVisible();
});
it("cancels a pending credential and preserves separate group connection", async () => {
  automaticApi();
  renderConnections();
  fireEvent.click(
    await screen.findByRole("button", { name: "Connect Telegram" }),
  );
  await screen.findByLabelText("Invitation link");
  fireEvent.click(screen.getByRole("button", { name: "Revoke invitation" }));
  await waitFor(() =>
    expect(screen.queryByLabelText("Invitation link")).not.toBeInTheDocument(),
  );
  expect(mockedApi.mock.calls.some(([path]) => path.endsWith("/revoke"))).toBe(
    true,
  );
});
it("connects a work group automatically and confirms disconnect", async () => {
  vi.useFakeTimers();
  automaticApi("WORK_GROUP");
  data.private = {
    ...data.private,
    approved: true,
    state: "CONNECTED",
    availability: "AVAILABLE",
    telegram_id: "123",
  };
  renderConnections();
  await act(async () => {});
  await act(async () =>
    fireEvent.click(screen.getByRole("button", { name: "Connect Work Group" })),
  );
  expect(
    screen.getByRole("link", { name: "Add Bot to Group" }),
  ).toHaveAttribute("href", expect.stringContaining("startgroup="));
  expect(screen.getByText(/Waiting for Telegram group/)).toBeVisible();
  data.group = {
    ...data.group,
    approved: true,
    state: "CONNECTED",
    availability: "AVAILABLE",
    display_name: "Demo HVAC",
    telegram_id: "-1001",
    invitation: null,
  };
  await act(async () => vi.advanceTimersByTimeAsync(2100));
  expect(screen.getByText("Work group connected")).toBeVisible();
  await act(async () =>
    fireEvent.click(
      screen.getByRole("button", { name: "Disconnect work group" }),
    ),
  );
  expect(
    mockedApi.mock.calls.some(([path]) => path.endsWith("/disconnect")),
  ).toBe(false);
  await act(async () =>
    fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" })),
  );
  expect(
    within(screen.getByTestId("WORK_GROUP")).getByText("Not connected"),
  ).toBeVisible();
  expect(
    within(screen.getByTestId("PRIVATE_TELEGRAM")).getByText("Connected"),
  ).toBeVisible();
});
it("stops failed polling and restarts on explicit retry", async () => {
  vi.useFakeTimers();
  automaticApi();
  renderConnections();
  await act(async () => {});
  await act(async () =>
    fireEvent.click(screen.getByRole("button", { name: "Connect Telegram" })),
  );
  mockedApi.mockRejectedValue(new Error("State unavailable"));
  await act(async () => vi.advanceTimersByTimeAsync(2100));
  const count = mockedApi.mock.calls.length;
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(mockedApi.mock.calls.length).toBe(count);
  mockedApi.mockResolvedValue(data);
  await act(async () =>
    fireEvent.click(screen.getByRole("button", { name: "Try again" })),
  );
  expect(mockedApi.mock.calls.length).toBeGreaterThan(count);
});
