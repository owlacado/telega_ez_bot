"use client";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type { ExpenseForm as FormState, ExpenseReceipt } from "@hub/contracts";
import { errorMessage } from "@/lib/api";

async function request<T>(
  token: string,
  suffix = "",
  payload?: unknown,
): Promise<T> {
  if (!/^[A-Za-z0-9_-]{43}$/.test(token))
    throw new Error("Open Expenses again in your private bot.");
  const response = await fetch(`/api/technician-forms/expense${suffix}`, {
    method: "POST",
    cache: "no-store",
    credentials: "omit",
    headers: {
      "Content-Type": "application/json",
      "X-Hub-Request": "1",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload ?? {}),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      body?.error?.details
        ?.map(
          (d: { field: string; message: string }) =>
            `${d.field.replace("body.", "")}: ${d.message}`,
        )
        .join("; ") ||
        body?.error?.message ||
        "Unable to save. Retry safely.",
    );
  return body;
}
export function ExpenseForm() {
  const token = useRef("");
  const pending = useRef(false);
  const opening = useRef<{ token: string; promise: Promise<FormState> } | null>(
    null,
  );
  const [form, setForm] = useState<FormState | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState<unknown>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    const currentToken = token.current;
    const entry =
      opening.current?.token === currentToken
        ? opening.current
        : { token: currentToken, promise: request<FormState>(currentToken) };
    opening.current = entry;
    const promise = entry.promise;
    try {
      const next = await promise;
      if (!signal?.aborted && currentToken === token.current) {
        setForm(next);
        setReceipt(next.expense_id ?? null);
        setError("");
      }
    } catch (reason) {
      if (!signal?.aborted && currentToken === token.current)
        setError(errorMessage(reason));
    } finally {
      if (opening.current === entry) opening.current = null;
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const openLink = (initial = false) => {
      const next = window.location.hash.slice(1);
      if (!initial && token.current === next) return;
      if (token.current !== next) {
        token.current = next;
        setForm(null);
        setReceipt(null);
        setError("");
        setRetry(null);
        pending.current = false;
        setBusy(false);
      }
      void load(controller.signal);
    };
    openLink(true);
    const changed = () => openLink();
    window.addEventListener("hashchange", changed);
    return () => {
      controller.abort();
      window.removeEventListener("hashchange", changed);
    };
  }, [load]);
  async function send(payload: unknown) {
    if (pending.current) return;
    const submittedToken = token.current;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await request<ExpenseReceipt>(
        token.current,
        "/submit",
        payload,
      );
      if (submittedToken !== token.current) return;
      setReceipt(result.expense_id);
      setRetry(null);
    } catch (reason) {
      if (submittedToken !== token.current) return;
      setRetry(payload);
      setError(errorMessage(reason));
    } finally {
      if (submittedToken === token.current) {
        pending.current = false;
        setBusy(false);
      }
    }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    void send({
      expense_type: fields.get("expense_type"),
      amount: fields.get("amount"),
      note: fields.get("note"),
    });
  }
  return (
    <main className="report-mobile">
      <header>
        <span className="eyebrow">TECHNICIAN HUB</span>
        <h1>Expenses</h1>
      </header>
      {receipt ? (
        <section className="panel report-success" role="status">
          <h2>Expense saved successfully.</h2>
          <p>Revision 1 · You can close this form.</p>
          <p className="expense-receipt">Receipt: {receipt}</p>
        </section>
      ) : (
        <>
          {error && (
            <div role="alert" className="error-notice">
              {error}
            </div>
          )}
          {!form ? (
            <>
              <p>Opening your secure form…</p>
              <button className="button" onClick={() => void load()}>
                Retry opening form
              </button>
            </>
          ) : (
            <>
              <p>
                <strong>{form.technician_name}</strong>
              </p>
              <p>
                Business date now: {form.expense_date} ·{" "}
                {form.accounting_timezone}
              </p>
              <p className="muted">
                The saved date uses your technician timezone at submission. It
                can change at midnight. This private link expires at{" "}
                {new Date(form.expires_at).toLocaleTimeString()}. Do not share
                it.
              </p>
              <form className="panel report-fields" onSubmit={submit}>
                <label>
                  Expense type
                  <input
                    name="expense_type"
                    required
                    maxLength={100}
                    autoComplete="off"
                  />
                </label>
                <label>
                  Amount ($)
                  <input
                    name="amount"
                    type="text"
                    inputMode="decimal"
                    required
                    pattern="[0-9]{1,10}(\.[0-9]{1,2})?"
                    maxLength={13}
                    autoComplete="off"
                  />
                </label>
                <label>
                  Note (optional)
                  <textarea name="note" maxLength={4000} rows={4} />
                </label>
                <p className="muted">
                  Receipt uploads are not supported. Keep any receipt photos in
                  your work group.
                </p>
                <button
                  className="button primary"
                  disabled={busy}
                  type="submit"
                >
                  {busy ? "Saving…" : "Save expense"}
                </button>
              </form>
              {retry !== null && (
                <button
                  className="button"
                  disabled={busy}
                  onClick={() => void send(retry)}
                >
                  Retry same submission
                </button>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
