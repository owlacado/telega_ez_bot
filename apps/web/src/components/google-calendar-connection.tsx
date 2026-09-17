"use client";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { GoogleConnection } from "@hub/contracts";
import { ApiError, api, errorMessage, json } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { ErrorNotice, Loading } from "./ui";
import { Modal } from "./modal";

export function GoogleCalendarConnection({
  onChange,
}: {
  onChange: () => void;
}) {
  const { data, error, reload } = useResource<GoogleConnection>(
    "/calendar-connections/google",
  );
  const [busy, setBusy] = useState("");
  const pending = useRef(false);
  const searchParams = useSearchParams();
  const result = searchParams.get("google");
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState(
    result && result !== "connected"
      ? "Google connection was not completed. Reconnect and choose the intended account."
      : "",
  );
  const [confirm, setConfirm] = useState<{
    kind: "SWITCH" | "DISCONNECT";
    snapshot: GoogleConnection;
  } | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (result) window.history.replaceState(null, "", "/calendars");
  }, [result]);

  async function action(
    kind: "CONNECT" | "RECONNECT" | "SWITCH" | "DISCONNECT" | "SCAN" | "EVENTS",
  ) {
    if (!data || pending.current) return;
    const snapshot = confirm?.snapshot ?? data;
    pending.current = true;
    setBusy(kind);
    setFailure("");
    setMessage("");
    let navigating = false;
    try {
      const expected = {
        expected_connection_id: snapshot.id,
        expected_generation: snapshot.generation,
      };
      if (kind === "SCAN") {
        const result = await api<{ discovered: number }>(
          "/calendar-connections/google/scan",
          { method: "POST" },
        );
        if (!mounted.current) return;
        setMessage(`Scan complete. ${result.discovered} calendars discovered.`);
      } else if (kind === "DISCONNECT") {
        await api("/calendar-connections/google/disconnect", {
          method: "POST",
          body: json({ ...expected, confirmation: "DISCONNECT" }),
        });
        if (!mounted.current) return;
        setMessage(
          "Disconnected. Catalog and assignments are preserved; Google calendars are unavailable.",
        );
      } else {
        const result = await api<{ authorization_url: string }>(
          "/calendar-connections/google/start",
          {
            method: "POST",
            body: json({
              ...expected,
              mode: kind === "EVENTS" ? "RECONNECT" : kind,
              request_event_access: kind === "EVENTS",
              confirm_replace: kind === "SWITCH",
              expected_impact_version: snapshot.impact_version,
            }),
          },
        );
        if (!mounted.current) return;
        window.location.assign(result.authorization_url);
        navigating = true;
        return;
      }
      setConfirm(null);
    } catch (error) {
      if (mounted.current) {
        setFailure(errorMessage(error));
        if (error instanceof ApiError && error.status === 409) setConfirm(null);
      }
    } finally {
      if (!navigating) {
        pending.current = false;
        if (mounted.current) {
          setBusy("");
          reload();
          onChange();
        }
      }
    }
  }
  return (
    <section
      className="panel google-panel"
      aria-label="Google Calendar connection"
    >
      <div className="panel-heading">
        <h2>Google Calendar</h2>
        <span className="micro-label">CALENDAR DISCOVERY</span>
      </div>
      <div className="panel-body">
        <ErrorNotice message={error} retry={reload} />
        {!data && !error && <Loading />}
        {data && (
          <>
            <strong>
              {data.status === "CONNECTED"
                ? "Connected"
                : data.status === "REAUTH_REQUIRED"
                  ? "Google Calendar connection needs attention"
                  : data.status === "ERROR"
                    ? "Google Calendar needs attention"
                    : "Not connected"}
            </strong>
            <p className="muted">
              {data.account_label ??
                "Connect your Google Calendar account to discover technician calendars automatically."}
            </p>
            {data.last_success_at && (
              <p className="field-hint">
                Last scan: {new Date(data.last_success_at).toLocaleString()}
              </p>
            )}
            {data.last_error_code && (
              <p role="status">
                {data.last_error_code.replaceAll("_", " ")}
                {data.retry_at
                  ? ` - Retry after ${new Date(data.retry_at).toLocaleString()}`
                  : ""}
              </p>
            )}
            {!data.enabled && (
              <p className="field-hint">
                Google OAuth is not configured on this server.
              </p>
            )}
            {data.status === "CONNECTED" && (
              <p className="field-hint">
                Calendar discovery available.{" "}
                {data.granted_scopes?.includes(
                  "https://www.googleapis.com/auth/calendar.events.readonly",
                )
                  ? "Google event access available."
                  : "Event access not yet granted."}
              </p>
            )}
            <div className="google-actions">
              {data.id &&
                !data.granted_scopes?.includes(
                  "https://www.googleapis.com/auth/calendar.events.readonly",
                ) && (
                  <button
                    className="button secondary"
                    disabled={!!busy || !data.enabled}
                    onClick={() => void action("EVENTS")}
                  >
                    Grant Event Access
                  </button>
                )}
              <button
                className="button primary"
                disabled={
                  !!busy ||
                  !data.enabled ||
                  !["CONNECTED", "ERROR"].includes(data.status)
                }
                onClick={() => void action("SCAN")}
              >
                {busy === "SCAN" ? "Scanning..." : "Scan Google Calendars"}
              </button>
              <button
                className="button secondary"
                disabled={!!busy || !data.enabled}
                onClick={() => void action(data.id ? "RECONNECT" : "CONNECT")}
              >
                {data.id
                  ? "Reconnect Google Calendar"
                  : "Connect Google Calendar"}
              </button>
              {data.id && (
                <button
                  className="button secondary"
                  disabled={!!busy || !data.enabled}
                  onClick={() => setConfirm({ kind: "SWITCH", snapshot: data })}
                >
                  Change Google account
                </button>
              )}
              {data.id && data.status !== "DISCONNECTED" && (
                <button
                  className="button secondary"
                  disabled={!!busy}
                  onClick={() =>
                    setConfirm({ kind: "DISCONNECT", snapshot: data })
                  }
                >
                  Disconnect
                </button>
              )}
            </div>
          </>
        )}
        {message && (
          <p role="status" className="save-notice">
            {message}
          </p>
        )}
        <ErrorNotice message={failure} />
      </div>
      {confirm && data && (
        <Modal
          title={
            confirm.kind === "SWITCH"
              ? "Replace Google account?"
              : "Disconnect Google Calendar?"
          }
          busy={!!busy}
          onClose={() => setConfirm(null)}
        >
          <p>
            {confirm.snapshot.calendar_count} discovered calendars and{" "}
            {confirm.snapshot.assignment_count} technician assignments may
            become unavailable.
          </p>
          <p className="muted">
            Your local catalog, exclusions, and assignment history will be
            preserved.{" "}
            {confirm.kind === "SWITCH"
              ? "Choose the new account on Google's consent screen."
              : "Google credential revocation can also remove other grants for this Google Cloud project."}
          </p>
          <ErrorNotice message={failure} />
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={!!busy}
              onClick={() => setConfirm(null)}
            >
              Cancel
            </button>
            <button
              className="button danger"
              disabled={!!busy}
              onClick={() => void action(confirm.kind)}
            >
              {busy
                ? "Working..."
                : confirm.kind === "SWITCH"
                  ? "Confirm account replacement"
                  : "Confirm disconnect"}
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
