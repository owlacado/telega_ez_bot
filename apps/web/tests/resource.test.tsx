import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  api: vi.fn(),
}));
const mockedApi = vi.mocked(api);
beforeEach(() => vi.resetAllMocks());
it("hides the previous identity immediately on navigation and after a 404", async () => {
  mockedApi
    .mockResolvedValueOnce({ id: "first" })
    .mockRejectedValueOnce(new Error("Technician not found."));
  const { result, rerender } = renderHook(
    ({ path }) => useResource<{ id: string }>(path),
    { initialProps: { path: "/technicians/first" } },
  );
  await waitFor(() => expect(result.current.data?.id).toBe("first"));
  rerender({ path: "/technicians/missing" });
  expect(result.current.data).toBeNull();
  await waitFor(() =>
    expect(result.current.error).toBe("Technician not found."),
  );
  expect(result.current.data).toBeNull();
});
it("ignores an old request even when transport completes after cancellation", async () => {
  let resolveOld!: (value: unknown) => void;
  mockedApi
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValueOnce({ id: "new" });
  const { result, rerender } = renderHook(
    ({ path }) => useResource<{ id: string }>(path),
    { initialProps: { path: "/old" } },
  );
  rerender({ path: "/new" });
  await waitFor(() => expect(result.current.data?.id).toBe("new"));
  await act(async () => resolveOld({ id: "old" }));
  expect(result.current.data?.id).toBe("new");
});
it("recovers from an unavailable API on retry", async () => {
  mockedApi
    .mockRejectedValueOnce(new Error("Offline"))
    .mockResolvedValueOnce([]);
  const { result } = renderHook(() => useResource<string[]>("/technicians"));
  await waitFor(() => expect(result.current.error).toBe("Offline"));
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.data).toEqual([]));
  expect(result.current.error).toBe("");
});

it("ignores a completed mutation belonging to a page already left", async () => {
  mockedApi
    .mockResolvedValueOnce({ id: "old" })
    .mockResolvedValueOnce({ id: "new" });
  const { result, rerender } = renderHook(
    ({ path }) => useResource<{ id: string }>(path),
    { initialProps: { path: "/old" } },
  );
  await waitFor(() => expect(result.current.data?.id).toBe("old"));
  const oldMutationCallback = result.current.setData;
  rerender({ path: "/new" });
  await waitFor(() => expect(result.current.data?.id).toBe("new"));
  act(() => oldMutationCallback({ id: "old edited" }));
  expect(result.current.data?.id).toBe("new");
});

it.each([true, false])(
  "keeps the newer reload when old success/failure arrives last (%s)",
  async (oldFails) => {
    let resolve!: (value: unknown) => void;
    let reject!: (error: Error) => void;
    mockedApi.mockImplementationOnce(
      () =>
        new Promise((ok, fail) => {
          resolve = ok;
          reject = fail;
        }),
    );
    if (oldFails) mockedApi.mockResolvedValueOnce({ status: "CONNECTED" });
    else mockedApi.mockRejectedValueOnce(new Error("Latest scan failed"));
    const { result } = renderHook(() =>
      useResource<{ status: string }>("/calendar-connections/google"),
    );
    act(() => result.current.reload());
    if (oldFails)
      await waitFor(() =>
        expect(result.current.data?.status).toBe("CONNECTED"),
      );
    else
      await waitFor(() =>
        expect(result.current.error).toBe("Latest scan failed"),
      );
    await act(async () => {
      if (oldFails) reject(new Error("Old failure"));
      else resolve({ status: "CONNECTED" });
    });
    if (oldFails) expect(result.current.error).toBe("");
    else {
      expect(result.current.error).toBe("Latest scan failed");
      expect(result.current.data).toBeNull();
    }
  },
);
