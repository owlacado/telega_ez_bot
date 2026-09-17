import "server-only";
import { cookies } from "next/headers";
import type { ManagerSession } from "@/components/auth-provider";

export async function serverSession(): Promise<ManagerSession | null> {
  const jar = await cookies();
  const token = jar.get("hub_session")?.value;
  if (!token) return null;
  const response = await fetch(
    `${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/api/auth/me`,
    { headers: { Cookie: `hub_session=${token}` }, cache: "no-store" },
  );
  if (response.status === 401) return null;
  if (!response.ok)
    throw new Error("The application is temporarily unavailable.");
  return response.json();
}
