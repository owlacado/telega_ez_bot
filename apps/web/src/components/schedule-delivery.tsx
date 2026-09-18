"use client";
import { useEffect, useRef, useState } from "react";
import type { DeliveryRead, ScheduleRead, DispatchRead } from "@hub/contracts";
import { api, errorMessage, json } from "@/lib/api";

const errors: Record<string, string> = {
  SCHEDULE_CHANGED: "Schedule changed. Refresh the preview before sending.",
  ALREADY_SENT:
    "This schedule was already sent. Use Resend if another copy is needed.",
  AMBIGUOUS_REQUIRES_RESEND:
    "Telegram may have accepted the previous message. Review the history and confirm a resend if needed.",
  DELIVERY_IN_PROGRESS:
    "A schedule for this date is already queued or processing.",
  TELEGRAM_UNAVAILABLE:
    "Connect an available Telegram destination before sending.",
  SCHEDULE_TOO_LARGE:
    "This schedule exceeds the single-message limit. Shorten the calendar titles or locations and refresh.",
  DELIVERY_DISABLED: "Schedule delivery is not configured.",
};
const label: Record<string, string> = {
  PENDING: "Queued",
  PROCESSING: "Sending",
  SENT: "Sent",
  FAILED: "Failed",
  AMBIGUOUS: "Outcome uncertain",
  CANCELLED: "Cancelled",
  WORK_GROUP: "Work group",
  PRIVATE: "Private Telegram",
  MANUAL: "Manual",
  AUTOMATIC: "Automatic",
  MANUAL_RESEND: "Resend",
};

export function ScheduleDelivery(props: {
  id: string;
  schedule: ScheduleRead | null;
  refresh: () => void;
}) {
  // Remount every identity: delayed A responses cannot become B's settings/history.
  return <Delivery key={props.id} {...props} />;
}
function Delivery({
  id,
  schedule,
  refresh,
}: {
  id: string;
  schedule: ScheduleRead | null;
  refresh: () => void;
}) {
  const [data, setData] = useState<DeliveryRead | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const [confirm, setConfirm] = useState<DispatchRead | null>(null);
  const alive = useRef(true);
  const submitting = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const started = Date.now();
    async function load() {
      try {
        const result = await api<DeliveryRead>(
          `/technicians/${id}/schedule-delivery`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setData(result);
        const active = result.history.some((d) =>
          ["PENDING", "PROCESSING"].includes(d.status),
        );
        if (!active)
          setNotice((previous) =>
            previous === "Schedule queued. Delivery has not yet been confirmed."
              ? ""
              : previous,
          );
        const ack = result.history.some(
          (d) => d.status === "SENT" && d.ack_status === "PENDING",
        );
        if (Date.now() - started < 600000 && (active || ack))
          timer = setTimeout(load, active ? 3000 : 30000);
      } catch {
        if (!controller.signal.aborted)
          setError("Unable to load delivery status. Refresh to try again.");
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [id, version]);
  async function mutate(action: () => Promise<unknown>, message: string) {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      if (alive.current) {
        setNotice(message);
        setConfirm(null);
        setVersion((v) => v + 1);
      }
    } catch (e) {
      if (alive.current) {
        const code = errorMessage(e);
        setError(
          errors[code] || "Unable to update delivery. Refresh and try again.",
        );
      }
    } finally {
      submitting.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const matching =
    data?.history.filter((d) => d.target_date === schedule?.operational_date) ??
    [];
  const pending = matching.some((d) =>
    ["PENDING", "PROCESSING"].includes(d.status),
  );
  const sent = matching.some(
    (d) => d.status === "SENT" && d.fingerprint === schedule?.fingerprint,
  );
  const uncertain = matching.some((d) => d.status === "AMBIGUOUS");
  const ready = !!(
    schedule?.state === "READY" &&
    schedule.fingerprint &&
    data?.available &&
    data.destination
  );
  function send(parent?: DispatchRead) {
    if (!ready) return;
    void mutate(
      () =>
        api(`/technicians/${id}/schedule-dispatches`, {
          method: "POST",
          body: json({
            target_date: schedule?.operational_date,
            fingerprint: schedule?.fingerprint,
            ...(parent
              ? { resend_of_id: parent.id, confirm_duplicate_risk: true }
              : {}),
          }),
        }),
      "Schedule queued. Delivery has not yet been confirmed.",
    );
  }
  return (
    <section aria-label="Schedule delivery" className="schedule-delivery">
      <h3>Telegram delivery</h3>
      {!data && !error && <p role="status">Loading delivery status...</p>}
      {data && (
        <>
          <p>
            Destination:{" "}
            <strong>
              {data.destination ? label[data.destination] : "Unavailable"}
            </strong>
          </p>
          {!data.available && <p>Schedule delivery is not configured.</p>}
          <label>
            <input
              type="checkbox"
              checked={data.enabled}
              disabled={busy || (!data.available && !data.enabled)}
              onChange={(e) => {
                const enabled = e.target.checked;
                void mutate(
                  () =>
                    api(`/technicians/${id}/schedule-delivery`, {
                      method: "PUT",
                      body: json({ enabled }),
                    }),
                  enabled
                    ? "Automatic delivery enabled."
                    : "Automatic delivery disabled.",
                );
              }}
            />
            Automatic schedule delivery
          </label>
          <p className="field-hint">
            When enabled, send at {data.local_time} in the assigned calendar
            timezone. Catch-up ends at 23:00.
          </p>
          {data.automatic_state && (
            <p>
              Latest automatic decision:{" "}
              {data.automatic_state.toLowerCase().replaceAll("_", " ")}
              {data.automatic_error
                ? ` (${data.automatic_error.toLowerCase().replaceAll("_", " ")})`
                : ""}
            </p>
          )}
          <button
            className="button"
            disabled={busy || !ready || pending || sent || uncertain}
            onClick={() => send()}
          >
            Send schedule
          </button>
          {sent && <p>This schedule was already sent.</p>}
          {!sent &&
            schedule?.fingerprint &&
            matching.some((d) => d.status === "SENT") && (
              <p>Schedule changed since last delivery.</p>
            )}
          {pending && <p role="status">A delivery is queued or processing.</p>}
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <button
        className="button secondary"
        disabled={busy}
        onClick={() => {
          setError("");
          setVersion((v) => v + 1);
          refresh();
        }}
      >
        Refresh preview and delivery status
      </button>
      {confirm && (
        <div role="group" aria-label="Confirm resend">
          <p>
            The previous message may already be in Telegram. Sending again can
            create a duplicate. This sends the currently previewed schedule as a
            new dispatch.
          </p>
          <button
            className="button danger"
            disabled={busy || !ready}
            onClick={() => send(confirm)}
          >
            Confirm resend
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setConfirm(null)}
          >
            Cancel resend
          </button>
        </div>
      )}
      <h4>Recent deliveries</h4>
      {data && !data.history.length && <p>No deliveries yet.</p>}
      <ol className="schedule-jobs">
        {data?.history.map((d) => (
          <li key={d.id}>
            <div>
              <strong>
                {d.target_date} · {label[d.status]}
              </strong>
              <p>
                {label[d.trigger]} · {label[d.destination]}
                {d.fallback_reason && (
                  <span>
                    {" "}
                    (requested {
                      label[d.requested_destination ?? "WORK_GROUP"]
                    };{" "}
                    {d.fallback_reason === "GROUP_UNAVAILABLE_BEFORE_SEND"
                      ? "group unavailable before send"
                      : "group rejected delivery"}
                    )
                  </span>
                )}{" "}
                · {d.job_count} jobs
              </p>
              {d.sent_at && <p>Sent {new Date(d.sent_at).toLocaleString()}</p>}
              {d.status === "SENT" && (
                <p>
                  {d.ack_status === "ACKNOWLEDGED"
                    ? `Acknowledged ${d.acknowledged_at ? new Date(d.acknowledged_at).toLocaleString() : ""}`
                    : "Awaiting acknowledgement"}
                </p>
              )}
              {d.status === "AMBIGUOUS" && (
                <p>
                  Telegram may have accepted this message. Automatic retry is
                  stopped.
                </p>
              )}
              {d.error_code && d.status !== "AMBIGUOUS" && (
                <p>{d.error_code.toLowerCase().replaceAll("_", " ")}</p>
              )}
              {["SENT", "FAILED", "AMBIGUOUS", "CANCELLED"].includes(
                d.status,
              ) &&
                d.target_date === schedule?.operational_date &&
                !data.history.some((child) => child.resend_of_id === d.id) && (
                  <button
                    className="button secondary"
                    disabled={busy || pending || !ready}
                    onClick={() => setConfirm(d)}
                  >
                    Resend schedule
                  </button>
                )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
