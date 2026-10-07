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
import { Check, Info, ReceiptText } from "lucide-react";
import styles from "./expense-form.module.css";

type Submission = { expense_type: string; amount: string; note: string };
type FieldName = "expense_type" | "amount" | "note";
type FieldErrors = Partial<Record<FieldName, string>>;
class FormRequestError extends Error {
  constructor(
    message: string,
    readonly fields: FieldErrors,
  ) {
    super(message);
  }
}
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
  if (!response.ok) {
    const fields: FieldErrors = {};
    for (const detail of body?.error?.details ?? []) {
      const name = detail.field.replace("body.", "");
      if (["expense_type", "amount", "note"].includes(name))
        fields[name as FieldName] = detail.message;
    }
    throw new FormRequestError(
      body?.error?.details
        ?.map(
          (d: { field: string; message: string }) =>
            `${d.field.replace("body.", "")}: ${d.message}`,
        )
        .join("; ") ||
        body?.error?.message ||
        "Unable to save. Retry safely.",
      fields,
    );
  }
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
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState<Submission | null>(null);
  const [saved, setSaved] = useState<Submission | null>(null);
  const [dateLoading, setDateLoading] = useState(false);
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
        setFieldErrors({});
        setDone(false);
        setSaved(null);
        setDateLoading(false);
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
  async function send(payload: Submission) {
    if (pending.current) return;
    const submittedToken = token.current;
    pending.current = true;
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      const result = await request<ExpenseReceipt>(
        token.current,
        "/submit",
        payload,
      );
      if (submittedToken !== token.current) return;
      setReceipt(result.expense_id);
      setSaved(payload);
      setRetry(null);
      // The preview date can cross midnight. Read the persisted business date
      // through the existing capability endpoint; never infer it from the clock.
      setDateLoading(true);
      void request<FormState>(submittedToken)
        .then((next) => {
          if (
            submittedToken === token.current &&
            next.status === "SUBMITTED" &&
            next.expense_id === result.expense_id
          )
            setForm(next);
        })
        .catch(() => {
          // Saving already succeeded. A summary read failure must not suggest
          // that a second financial submission is needed.
        })
        .finally(() => {
          if (submittedToken === token.current) setDateLoading(false);
        });
    } catch (reason) {
      if (submittedToken !== token.current) return;
      setRetry(payload);
      if (reason instanceof FormRequestError) setFieldErrors(reason.fields);
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
      expense_type: String(fields.get("expense_type") ?? ""),
      amount: String(fields.get("amount") ?? ""),
      note: String(fields.get("note") ?? ""),
    });
  }
  function fieldProps(name: FieldName) {
    return {
      "aria-invalid": fieldErrors[name] ? true : undefined,
      "aria-describedby": fieldErrors[name] ? `${name}-error` : undefined,
      onInvalid: (event: FormEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        const message = event.currentTarget.validationMessage;
        setFieldErrors((previous) => ({ ...previous, [name]: message }));
      },
      onChange: () =>
        setFieldErrors((previous) => ({ ...previous, [name]: undefined })),
    };
  }
  function fieldError(name: FieldName) {
    return fieldErrors[name] ? (
      <span id={`${name}-error`} className={styles.fieldError}>
        {fieldErrors[name]}
      </span>
    ) : null;
  }
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <span className={styles.brand}>
          <ReceiptText size={18} aria-hidden="true" /> TECHNICIAN HUB
        </span>
        <h1>Expenses</h1>
        <p>A simple record of your work expenses.</p>
      </header>
      {receipt ? (
        <section className={styles.success} role="status">
          <span className={styles.successIcon}>
            <Check size={28} aria-hidden="true" />
          </span>
          <h2>Expense saved successfully.</h2>
          <dl className={styles.summary}>
            {saved && (
              <>
                <div>
                  <dt>Amount</dt>
                  <dd className={styles.amount}>
                    ${saved.amount.replace(/^0+(?=\d)/, "").split(".")[0]}.
                    {(saved.amount.split(".")[1] ?? "").padEnd(2, "0")}
                  </dd>
                </div>
                <div>
                  <dt>Expense type</dt>
                  <dd>{saved.expense_type.trim()}</dd>
                </div>
              </>
            )}
            <div>
              <dt>Business date</dt>
              <dd>
                {form?.expense_id === receipt
                  ? form.expense_date
                  : dateLoading
                    ? "Loading saved date..."
                    : "Unavailable"}
              </dd>
            </div>
            {form?.expense_id === receipt && (
              <div>
                <dt>Timezone</dt>
                <dd>{form.accounting_timezone}</dd>
              </div>
            )}
          </dl>
          <p>
            {done
              ? "All done. Close this tab to return to Telegram."
              : "You can close this form and return to Telegram."}
          </p>
          {!done && (
            <button
              type="button"
              className={styles.primary}
              onClick={() => {
                setDone(true);
                // Browsers only allow closing script-opened windows. Keep a useful
                // fallback for normal tabs without loading the Telegram SDK.
                if (window.opener) window.close();
              }}
            >
              Done
            </button>
          )}
        </section>
      ) : (
        <>
          {error && (
            <div id="expense-error" role="alert" className={styles.error}>
              {error}
            </div>
          )}
          {!form ? (
            <>
              <p className={styles.loading}>Opening your secure form…</p>
              <button className={styles.secondary} onClick={() => void load()}>
                Retry opening form
              </button>
            </>
          ) : (
            <>
              <section className={styles.context} aria-label="Expense context">
                <span className={styles.contextLabel}>Technician</span>
                <strong>{form.technician_name}</strong>
                <dl>
                  <div>
                    <dt>Business date now</dt>
                    <dd>{form.expense_date ?? "Unavailable"}</dd>
                  </div>
                  <div>
                    <dt>Timezone</dt>
                    <dd>{form.accounting_timezone ?? "Unavailable"}</dd>
                  </div>
                </dl>
              </section>
              <form
                className={styles.form}
                onSubmit={submit}
                aria-describedby={error ? "expense-error" : undefined}
              >
                <div className={styles.field}>
                  <label htmlFor="expense-type">Expense type</label>
                  <input
                    id="expense-type"
                    {...fieldProps("expense_type")}
                    name="expense_type"
                    required
                    maxLength={100}
                    autoComplete="off"
                  />
                  {fieldError("expense_type")}
                </div>
                <div className={styles.field}>
                  <label htmlFor="expense-amount">Amount ($)</label>
                  <input
                    id="expense-amount"
                    {...fieldProps("amount")}
                    name="amount"
                    type="text"
                    inputMode="decimal"
                    required
                    pattern="[0-9]{1,10}(\.[0-9]{1,2})?"
                    maxLength={13}
                    autoComplete="off"
                  />
                  {fieldError("amount")}
                </div>
                <div className={styles.field}>
                  <label htmlFor="expense-note">Note (optional)</label>
                  <textarea
                    id="expense-note"
                    {...fieldProps("note")}
                    name="note"
                    maxLength={4000}
                    rows={3}
                  />
                  {fieldError("note")}
                </div>
                <div className={styles.help}>
                  <Info size={18} aria-hidden="true" />
                  <p>Receipt photos can be sent to your Work Group.</p>
                </div>
                <button
                  className={styles.primary}
                  disabled={busy}
                  type="submit"
                >
                  {busy ? "Saving…" : "Save expense"}
                </button>
              </form>
              <p className={styles.privacy}>
                The saved date uses your technician timezone at submission and
                can change at midnight. This private link expires at{" "}
                {new Date(form.expires_at).toLocaleTimeString()}. Do not share
                it.
              </p>
              {retry !== null && (
                <button
                  className={styles.secondary}
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
