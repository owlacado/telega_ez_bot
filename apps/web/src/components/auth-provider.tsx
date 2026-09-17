"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { ManagerSession } from "@hub/contracts";
export type { ManagerSession } from "@hub/contracts";
const AuthContext = createContext<ManagerSession | null>(null);
export const useManager = () => useContext(AuthContext);
export function AuthProvider({
  manager,
  children,
}: {
  manager: ManagerSession;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [valid, setValid] = useState(true);
  useEffect(() => {
    const expired = () => {
      setValid(false);
      router.replace("/login");
      router.refresh();
    };
    const check = () => {
      if (!document.hidden) void api("/auth/me").catch(() => {});
    };
    window.addEventListener("hub:unauthenticated", expired);
    document.addEventListener("visibilitychange", check);
    const interval = window.setInterval(check, 60_000);
    return () => {
      window.removeEventListener("hub:unauthenticated", expired);
      document.removeEventListener("visibilitychange", check);
      clearInterval(interval);
    };
  }, [router]);
  return (
    <AuthContext.Provider value={manager}>
      {valid ? children : <p className="loading">Returning to sign in…</p>}
    </AuthContext.Provider>
  );
}
