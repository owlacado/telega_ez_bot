"use client";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { GoogleConnection } from "@hub/contracts";
import { api, errorMessage, json } from "@/lib/api";
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
  const [message, setMessage] = useState(
    result === "connected"
      ? "Google Calendar connected. You can scan calendars now."
      : "",
  );
  const [failure, setFailure] = useState(
    result && result !== "connected"
      ? "Google connection was not completed. Reconnect and choose the intended account."
      : "",
  );
  const [confirm, setConfirm] = useState<"SWITCH" | "DISCONNECT" | null>(null);
  useEffect(() => {
    if (result) window.history.replaceState(null, "", "/calendars");
  }, [result]);

  async function action(
    kind: "CONNECT" | "RECONNECT" | "SWITCH" | "DISCONNECT" | "SCAN",
  ) {
    if (!data || pending.current) return;
    pending.current = true;
    setBusy(kind);
    setFailure("");
    setMessage("");
    try {
      const expected = {
        expected_connection_id: data.id,
        expected_generation: data.generation,
      };
      if (kind === "SCAN") {
        const result = await api<{ discovered: number }>(
          "/calendar-connections/google/scan",
          { method: "POST" },
        );
        setMessage(`Scan complete. ${result.discovered} calendars discovered.`);
      } else if (kind === "DISCONNECT") {
        await api("/calendar-connections/google/disconnect", {
          method: "POST",
          body: json({ ...expected, confirmation: "DISCONNECT" }),
        });
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
              mode: kind,
              confirm_replace: kind === "SWITCH",
            }),
          },
        );
        window.location.assign(result.authorization_url);
        return;
      }
      setConfirm(null);
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      pending.current = false;
      setBusy("");
      reload();
      onChange();
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
                    ? "Last scan failed"
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
                  ? ` - Retry after ${new Date(data.retry_at).toLocaleTimeString()}`
                  : ""}
              </p>
            )}
            {!data.enabled && (
              <p className="field-hint">
                Google OAuth is not configured on this server.
              </p>
            )}
            <div className="google-actions">
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
                  onClick={() => setConfirm("SWITCH")}
                >
                  Change Google account
                </button>
              )}
              {data.id && data.status !== "DISCONNECTED" && (
                <button
                  className="button secondary"
                  disabled={!!busy}
                  onClick={() => setConfirm("DISCONNECT")}
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
            confirm === "SWITCH"
              ? "Replace Google account?"
              : "Disconnect Google Calendar?"
          }
          busy={!!busy}
          onClose={() => setConfirm(null)}
        >
          <p>
            {data.calendar_count} discovered calendars and{" "}
            {data.assignment_count} technician assignments may become
            unavailable.
          </p>
          <p className="muted">
            Your local catalog, exclusions, and assignment history will be
            preserved.{" "}
            {confirm === "SWITCH"
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
              onClick={() => void action(confirm)}
            >
              {busy
                ? "Working..."
                : confirm === "SWITCH"
                  ? "Confirm account replacement"
                  : "Confirm disconnect"}
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
