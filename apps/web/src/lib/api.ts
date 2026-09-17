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
  const response = await fetch(`/api${path}`, {
    ...options,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
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
