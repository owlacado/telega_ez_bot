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
    const fields = body?.error?.details
      ?.map(
        (item: { field: string; message: string }) =>
          `${item.field.replace("body.", "")}: ${item.message}`,
      )
      .join(" · ");
    throw new ApiError(
      fields || body?.error?.message || `Request failed (${response.status}).`,
      response.status,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const json = (value: unknown) => JSON.stringify(value);
export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}
