import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
afterEach(() => vi.unstubAllGlobals());
it("shows a recoverable message for malformed JSON", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("broken", { status: 200 })),
  );
  await expect(api("/technicians")).rejects.toThrow("invalid response");
});
it("handles an unexpected error envelope without throwing a TypeError", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { details: {}, message: { unexpected: true } },
        }),
        { status: 503 },
      ),
    ),
  );
  await expect(api("/technicians")).rejects.toEqual(
    new ApiError("Request failed (503).", 503),
  );
});
it("handles empty success responses", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "test-token" }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 })),
  );
  await expect(
    api("/technicians/id", { method: "DELETE" }),
  ).resolves.toBeUndefined();
});
