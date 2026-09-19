import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError, download } from "@/lib/api";
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
it("downloads a non-empty XLSX with the server filename", async () => {
  const click = vi.fn();
  const createObjectURL = vi.fn().mockReturnValue("blob:synthetic");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
  vi.spyOn(document, "createElement").mockReturnValue({
    click,
    href: "",
    download: "",
  } as unknown as HTMLAnchorElement);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(new Blob(["xlsx-bytes"]), {
        status: 200,
        headers: {
          "Content-Type":
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "Content-Disposition":
            'attachment; filename="Synthetic_2026-09-14_2026-09-20.xlsx"',
        },
      }),
    ),
  );
  await expect(download("/accounting/weekly/all.xlsx")).resolves.toBe(
    "Synthetic_2026-09-14_2026-09-20.xlsx",
  );
  expect(click).toHaveBeenCalledOnce();
  expect(createObjectURL).toHaveBeenCalledOnce();
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic");
});
it("rejects empty or non-XLSX download responses", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response("not a workbook", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(null, {
          status: 200,
          headers: {
            "Content-Type":
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          },
        }),
      ),
  );
  await expect(download("/first")).rejects.toThrow("invalid workbook");
  await expect(download("/second")).rejects.toThrow("empty workbook");
});
