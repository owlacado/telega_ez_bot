"use client";

import type { AccountingMirrorStatus, GoogleConnection } from "@hub/contracts";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, api, errorMessage, json } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { ErrorNotice } from "./ui";

const labels: Record<AccountingMirrorStatus["state"], string> = {
  NOT_CONFIGURED: "Not configured",
  NEEDS_PERMISSION: "Google Sheets permission required",
  READY: "Ready to sync",
  DISABLED: "Automatic sync disabled",
  PENDING: "Sync queued",
  SYNCING: "Syncing",
  SYNCED: "Synced",
  FAILED: "Sync needs attention",
  NEEDS_AUTH: "Google reconnect required",
};

export function AccountingMirror({
  technicianId,
  weekStart,
  allTechnicians = false,
}: {
  technicianId: string;
  weekStart: string;
  allTechnicians?: boolean;
}) {
  const base = allTechnicians
    ? "/accounting/weekly/all/mirror"
    : `/technicians/${technicianId}/accounting/mirror`;
  const path = `${base}?week_start=${weekStart}`;
  const identity = path;
  const { data, error, reload, setData } =
    useResource<AccountingMirrorStatus>(path);
  const currentIdentity = useRef(identity);
  useLayoutEffect(() => {
    currentIdentity.current = identity;
  }, [identity]);
  const [spreadsheetState, setSpreadsheetState] = useState({
    identity,
    value: "",
  });
  const [busyState, setBusyState] = useState({ identity: "", value: "" });
  const [failureState, setFailureState] = useState({
    identity: "",
    value: "",
  });
  const pending = useRef<string | null>(null);
  const spreadsheet =
    spreadsheetState.identity === identity ? spreadsheetState.value : "";
  const busy = busyState.identity === identity ? busyState.value : "";
  const failure = failureState.identity === identity ? failureState.value : "";

  useEffect(() => {
    if (!data || !["PENDING", "SYNCING"].includes(data.state)) return;
    const timer = window.setInterval(reload, 2000);
    return () => window.clearInterval(timer);
  }, [data, reload]);

  async function configure() {
    if (pending.current === identity || !spreadsheet.trim()) return;
    const requestIdentity = identity;
    const requestedSpreadsheet = spreadsheet.trim();
    const replacing = Boolean(
      data?.configured && data.spreadsheet_id !== requestedSpreadsheet,
    );
    if (
      replacing &&
      !window.confirm(
        "Replace this mirror destination? Existing Google Sheets content is preserved.",
      )
    )
      return;
    pending.current = requestIdentity;
    setBusyState({ identity: requestIdentity, value: "CONFIGURE" });
    setFailureState({ identity: requestIdentity, value: "" });
    try {
      const next = await api<AccountingMirrorStatus>(path, {
        method: "PUT",
        body: json({ spreadsheet: requestedSpreadsheet, replace: replacing }),
      });
      if (currentIdentity.current === requestIdentity) {
        setData(next);
        setSpreadsheetState({ identity: requestIdentity, value: "" });
      }
    } catch (reason) {
      if (currentIdentity.current === requestIdentity)
        setFailureState({
          identity: requestIdentity,
          value: errorMessage(reason),
        });
    } finally {
      if (pending.current === requestIdentity) pending.current = null;
      if (currentIdentity.current === requestIdentity)
        setBusyState({ identity: requestIdentity, value: "" });
    }
  }

  async function action(value: "ENABLE" | "DISABLE" | "REMOVE" | "SYNC") {
    if (!data?.target_generation || pending.current === identity) return;
    const requestIdentity = identity;
    if (
      value === "REMOVE" &&
      !window.confirm(
        "Remove this mirror configuration? Existing Google Sheets content is preserved.",
      )
    )
      return;
    pending.current = requestIdentity;
    setBusyState({ identity: requestIdentity, value });
    setFailureState({ identity: requestIdentity, value: "" });
    try {
      const next = await api<AccountingMirrorStatus>(
        `${base}/action?week_start=${weekStart}`,
        {
          method: "POST",
          body: json({
            action: value,
            expected_generation: data.target_generation,
          }),
        },
      );
      if (currentIdentity.current === requestIdentity) setData(next);
    } catch (reason) {
      if (currentIdentity.current === requestIdentity) {
        setFailureState({
          identity: requestIdentity,
          value: errorMessage(reason),
        });
        if (reason instanceof ApiError && reason.status === 409) reload();
      }
    } finally {
      if (pending.current === requestIdentity) pending.current = null;
      if (currentIdentity.current === requestIdentity)
        setBusyState({ identity: requestIdentity, value: "" });
    }
  }

  async function grantPermission() {
    if (pending.current === identity) return;
    const requestIdentity = identity;
    pending.current = requestIdentity;
    setBusyState({ identity: requestIdentity, value: "PERMISSION" });
    setFailureState({ identity: requestIdentity, value: "" });
    try {
      const connection = await api<GoogleConnection>(
        "/calendar-connections/google",
      );
      if (!connection.id || !connection.generation)
        throw new Error(
          "Connect Google Calendar before granting Sheets access.",
        );
      const result = await api<{ authorization_url: string }>(
        "/calendar-connections/google/start",
        {
          method: "POST",
          body: json({
            mode: "RECONNECT",
            request_sheets_access: true,
            expected_connection_id: connection.id,
            expected_generation: connection.generation,
            expected_impact_version: connection.impact_version,
          }),
        },
      );
      if (currentIdentity.current === requestIdentity)
        window.location.assign(result.authorization_url);
    } catch (reason) {
      if (pending.current === requestIdentity) pending.current = null;
      if (currentIdentity.current === requestIdentity) {
        setBusyState({ identity: requestIdentity, value: "" });
        setFailureState({
          identity: requestIdentity,
          value: errorMessage(reason),
        });
      }
    }
  }

  return (
    <section
      className="accounting-mirror"
      aria-label={`${allTechnicians ? "All Tech" : "Technician"} Google Sheets mirror`}
    >
      <div className="panel-heading">
        <h4>
          {allTechnicians ? "All Tech Google Sheet" : "Technician Google Sheet"}
        </h4>
        {data && <span className="micro-label">{labels[data.state]}</span>}
      </div>
      <ErrorNotice
        message={error || failure}
        retry={error ? reload : undefined}
      />
      <p className="muted">
        Mirrors this week into an existing spreadsheet. Technician Hub creates
        or updates the dated tab only.
      </p>
      {data?.configured && (
        <p>
          <strong>{data.spreadsheet_id}</strong>{" "}
          {data.open_url && (
            <a href={data.open_url} target="_blank" rel="noopener noreferrer">
              Open Google Sheet
            </a>
          )}
        </p>
      )}
      {data?.last_success_at && (
        <p className="field-hint">
          Last synced {new Date(data.last_success_at).toLocaleString()}
        </p>
      )}
      {data?.last_error_code && (
        <p role="status">{data.last_error_code.replaceAll("_", " ")}</p>
      )}
      {data?.worker_state !== "RUNNING" && data?.configured && (
        <p className="field-hint">
          Mirror worker is {data.worker_state.toLowerCase()}.
        </p>
      )}
      <div className="accounting-navigation">
        <label>
          Existing Spreadsheet ID or URL
          <input
            value={spreadsheet}
            onChange={(event) =>
              setSpreadsheetState({ identity, value: event.target.value })
            }
            placeholder={data?.spreadsheet_id || "Google Sheets URL or ID"}
          />
        </label>
        <button
          className="button"
          disabled={!!busy || !spreadsheet.trim()}
          onClick={() => void configure()}
        >
          {busy === "CONFIGURE"
            ? "Saving…"
            : data?.configured
              ? "Replace destination"
              : "Configure"}
        </button>
        {data?.auth_state === "NEEDS_PERMISSION" && (
          <button
            className="button"
            disabled={!!busy}
            onClick={() => void grantPermission()}
          >
            {busy === "PERMISSION"
              ? "Opening Google…"
              : "Grant Sheets permission"}
          </button>
        )}
        {data && ["NEEDS_AUTH", "NOT_CONNECTED"].includes(data.auth_state) && (
          <a className="button" href="/calendars">
            Reconnect Google
          </a>
        )}
        {data?.configured && data.enabled && data.auth_state === "READY" && (
          <button
            className="button primary"
            disabled={!!busy}
            onClick={() => void action("SYNC")}
          >
            {busy === "SYNC" ? "Queueing…" : "Sync this week"}
          </button>
        )}
        {data?.configured && (
          <button
            className="button"
            disabled={!!busy}
            onClick={() => void action(data.enabled ? "DISABLE" : "ENABLE")}
          >
            {data.enabled ? "Disable automatic sync" : "Enable automatic sync"}
          </button>
        )}
        {data?.configured && (
          <button
            className="button danger"
            disabled={!!busy}
            onClick={() => void action("REMOVE")}
          >
            Remove mirror
          </button>
        )}
      </div>
    </section>
  );
}
