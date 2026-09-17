"use client";
import { useState } from "react";
import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useManager } from "./auth-provider";
import { api, errorMessage } from "@/lib/api";
export function ManagerMenu() {
  const manager = useManager();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function logout() {
    setBusy(true);
    setError("");
    try {
      await api("/auth/logout", { method: "POST" });
      router.replace("/login");
      router.refresh();
    } catch (error) {
      setError(errorMessage(error));
      setBusy(false);
    }
  }
  return (
    <>
      <div className="user-area">
        <span className="user-avatar">M</span>
        <span className="user-name">
          {manager?.username ?? "Manager"}
          <small>Authenticated workspace</small>
        </span>
        <button
          className="icon-button logout-button"
          onClick={logout}
          disabled={busy}
          aria-label="Sign out"
          title="Sign out"
        >
          <LogOut size={16} />
        </button>
      </div>
      {error && (
        <p role="alert" className="logout-error">
          {error}
        </p>
      )}
    </>
  );
}
