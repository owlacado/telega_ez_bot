"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type { WorkReportForm as FormState } from "@hub/contracts";
import { errorMessage } from "@/lib/api";

export const paymentLabels: Record<string, string> = {
  CASH: "Cash",
  ZELLE: "Zelle",
  CHECK: "Check",
  CREDIT_CARD: "Credit Card / Cash App",
  VENMO: "Venmo",
  SUPER: "SUPER",
  ESTIMATE: "Estimate",
  CANCEL: "Cancel",
};

async function formRequest<T>(
  token: string,
  suffix = "",
  payload?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  if (!/^[A-Za-z0-9_-]{43}$/.test(token))
    throw new Error(
      "This form is unavailable. Open Submit Report in your private bot.",
    );
  const response = await fetch(`/api/technician-forms/work-report${suffix}`, {
    method: "POST",
    cache: "no-store",
    credentials: "omit",
    signal,
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
      body?.error?.message ?? "Unable to submit. Please try again.",
    );
  return body;
}

export function WorkReportForm() {
  const token = useRef("");
  const busyRef = useRef(false);
  const [form, setForm] = useState<FormState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [payment, setPayment] = useState("");
  const [amount, setAmount] = useState("");
  const [retryPayload, setRetryPayload] = useState<unknown>(null);
  const forcedZero = Boolean(
    form?.zero_amount_choices?.some((value) => value === payment),
  );
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await formRequest<FormState>(
        token.current,
        "",
        undefined,
        signal,
      );
      if (!signal?.aborted) {
        setForm(next);
        setSuccess(next.status === "SUBMITTED");
        setError("");
      }
    } catch (reason) {
      if (!signal?.aborted) setError(errorMessage(reason));
    }
  }, []);
  useEffect(() => {
    token.current = window.location.hash.slice(1);
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function select(choice_id: string) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      setForm(
        await formRequest<FormState>(token.current, "/select", { choice_id }),
      );
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function send(payload: unknown) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await formRequest(token.current, "/submit", payload);
      setSuccess(true);
      setRetryPayload(null);
    } catch (reason) {
      setRetryPayload(payload);
      setError(
        `${errorMessage(reason)} If the response was lost, retry the same submission safely.`,
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    void send({
      amount_closed: forcedZero ? "0.00" : amount,
      payment_method: payment,
      closed_by: fields.get("closed_by"),
      comments: fields.get("comments"),
      yearly_maintenance_plan_provided: fields.get("maintenance") === "yes",
      reviews: {
        GOOGLE: Number(fields.get("GOOGLE")),
        GROUPON: Number(fields.get("GROUPON")),
        FACEBOOK: Number(fields.get("FACEBOOK")),
      },
    });
  }
  return (
    <main className="report-mobile">
      <header>
        <span className="eyebrow">TECHNICIAN HUB</span>
        <h1>Submit Report</h1>
      </header>
      {success ? (
        <section className="panel report-success" role="status">
          <h2>Report submitted successfully.</h2>
          <p>Your report is saved. You can close this form.</p>
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
              <p className="muted">
                This private form expires at{" "}
                {new Date(form.expires_at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                . Do not share this link.
              </p>
              {!form.selected ? (
                <section aria-label="Today's jobs">
                  <h2>Select today&apos;s job</h2>
                  {(form.jobs ?? []).length === 0 && (
                    <p>No scheduled jobs found for today.</p>
                  )}
                  {(form.jobs ?? []).map((job) => (
                    <button
                      key={job.choice_id}
                      className="report-job"
                      disabled={busy || job.submitted}
                      onClick={() => void select(job.choice_id)}
                    >
                      <strong>
                        {job.start_time}–{job.end_time} · {job.title}
                      </strong>
                      <span>{job.location}</span>
                      {job.submitted && <span>Submitted</span>}
                    </button>
                  ))}
                </section>
              ) : (
                <>
                  <section className="report-job">
                    <strong>
                      {form.selected.start_time} · {form.selected.title}
                    </strong>
                    <span>{form.selected.location}</span>
                    <span>{form.selected.operational_date}</span>
                  </section>
                  <form onSubmit={submit}>
                    <fieldset disabled={busy || Boolean(retryPayload)}>
                      <label>
                        Type of payment
                        <select
                          required
                          value={payment}
                          onChange={(event) => {
                            setPayment(event.target.value);
                            if (
                              form.zero_amount_choices?.some(
                                (value) => value === event.target.value,
                              )
                            )
                              setAmount("0.00");
                          }}
                        >
                          <option value="">Choose payment / outcome</option>
                          {form.payment_choices?.map((value) => (
                            <option key={value} value={value}>
                              {paymentLabels[value]}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Amount of closed project ($)
                        <input
                          required
                          type="text"
                          inputMode="decimal"
                          pattern="[0-9]{1,10}(\.[0-9]{1,2})?"
                          maxLength={13}
                          value={forcedZero ? "0.00" : amount}
                          readOnly={forcedZero}
                          onChange={(event) => setAmount(event.target.value)}
                        />
                      </label>
                      {forcedZero && (
                        <p>
                          Amount is always $0.00 for {paymentLabels[payment]}.
                        </p>
                      )}
                      <label>
                        Who closed this project?
                        <select name="closed_by" required defaultValue="">
                          <option value="">Choose closer</option>
                          <option value="MYSELF">Myself</option>
                          <option value="CALL_CENTER">Call center</option>
                        </select>
                      </label>
                      <div className="report-review-grid">
                        {["GOOGLE", "GROUPON", "FACEBOOK"].map((platform) => (
                          <label key={platform}>
                            {platform[0] + platform.slice(1).toLowerCase()}{" "}
                            reviews
                            <input
                              name={platform}
                              type="number"
                              inputMode="numeric"
                              min="0"
                              max="100"
                              step="1"
                              required
                              placeholder="0"
                            />
                          </label>
                        ))}
                      </div>
                      <label>
                        Yearly maintenance plan provided
                        <select name="maintenance" required defaultValue="">
                          <option value="">Choose Yes / No</option>
                          <option value="no">No</option>
                          <option value="yes">Yes</option>
                        </select>
                      </label>
                      <label>
                        Job description &amp; comments (optional)
                        <textarea name="comments" maxLength={4000} rows={4} />
                      </label>
                      <button
                        className="button primary"
                        type="submit"
                        disabled={busy}
                      >
                        {busy ? "Submitting…" : "Submit report"}
                      </button>
                    </fieldset>
                  </form>
                  {Boolean(retryPayload) && (
                    <div>
                      <button
                        className="button primary"
                        disabled={busy}
                        onClick={() => void send(retryPayload)}
                      >
                        Retry same submission
                      </button>
                      <button
                        className="button"
                        disabled={busy}
                        onClick={() => {
                          setRetryPayload(null);
                          void load();
                        }}
                      >
                        Check saved state / edit
                      </button>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
