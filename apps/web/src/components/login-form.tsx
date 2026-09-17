"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { LockKeyhole, Wrench } from "lucide-react";
import { api, errorMessage, json } from "@/lib/api";
import { ErrorNotice } from "./ui";
export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      await api("/auth/login", {
        method: "POST",
        body: json({
          username: form.get("username"),
          password: form.get("password"),
        }),
      });
      router.replace("/");
      router.refresh();
    } catch (error) {
      setError(errorMessage(error));
      setBusy(false);
    }
  }
  return (
    <div className="login-screen">
      <div className="login-card">
        <span className="brand-mark">
          <Wrench size={22} />
        </span>
        <div className="eyebrow">TECHNICIAN HUB</div>
        <h1>Welcome back.</h1>
        <p className="muted">Sign in to your local manager workspace.</p>
        <form onSubmit={submit}>
          <label>
            Username
            <input
              name="username"
              autoComplete="username"
              required
              maxLength={100}
              autoFocus
            />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
            />
          </label>
          <ErrorNotice message={error} />
          <button className="button primary" disabled={busy}>
            <LockKeyhole size={16} />
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="field-hint">
          Manager accounts are provisioned locally. Contact your workspace
          administrator for access.
        </p>
      </div>
    </div>
  );
}
