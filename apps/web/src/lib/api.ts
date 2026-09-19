export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Hub-Request": "1",
  };
  if (
    options.method &&
    !["GET", "HEAD"].includes(options.method.toUpperCase()) &&
    path !== "/auth/login"
  ) {
    const session = await api<{ csrf_token: string }>("/auth/me");
    headers["X-CSRF-Token"] = session.csrf_token;
  }
  const response = await fetch(`/api${path}`, {
    ...options,
    cache: "no-store",
    credentials: "same-origin",
    headers: { ...headers, ...options.headers },
  });
  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== "/auth/login" &&
      typeof window !== "undefined"
    )
      window.dispatchEvent(new Event("hub:unauthenticated"));
    const body = await response.json().catch(() => null);
    const details = body?.error?.details;
    const fields = Array.isArray(details)
      ? details
          .filter(
            (item) =>
              typeof item?.field === "string" &&
              typeof item?.message === "string",
          )
          .map((item) => `${item.field.replace("body.", "")}: ${item.message}`)
          .join(" ; ")
      : "";
    throw new ApiError(
      fields ||
        (typeof body?.error?.message === "string"
          ? body.error.message
          : `Request failed (${response.status}).`),
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  try {
    return await response.json();
  } catch {
    throw new ApiError(
      "The server returned an invalid response. Please try again.",
      response.status,
    );
  }
}

const XLSX_TYPE =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export async function download(path: string): Promise<string> {
  const response = await fetch(`/api${path}`, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { "X-Hub-Request": "1" },
  });
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined")
      window.dispatchEvent(new Event("hub:unauthenticated"));
    const body = await response.json().catch(() => null);
    throw new ApiError(
      typeof body?.error?.message === "string"
        ? body.error.message
        : `Download failed (${response.status}).`,
      response.status,
    );
  }
  if (!response.headers.get("content-type")?.startsWith(XLSX_TYPE))
    throw new ApiError(
      "The server returned an invalid workbook. Please try again.",
      response.status,
    );
  const blob = await response.blob();
  if (blob.size === 0)
    throw new ApiError(
      "The server returned an empty workbook. Please try again.",
      response.status,
    );
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="([A-Za-z0-9_.-]+)"/);
  const filename = match?.[1] || "weekly-accounting.xlsx";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
  return filename;
}
export const json = (value: unknown) => JSON.stringify(value);
export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}
