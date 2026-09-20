"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, Link2, MapPin, Save, UserRound } from "lucide-react";
import type {
  Calendar,
  TechnicianDetail,
  TechnicianUpdate,
} from "@hub/contracts";
import { ApiError, api, errorMessage, json } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { DisabledAction, ErrorNotice } from "./ui";
import { AccountingTimezone } from "./accounting-timezone";
import { TelegramConnections } from "./telegram-connections";
export function ProfilePanel({
  technician: t,
  onUpdate,
  onMissing,
}: {
  technician: TechnicianDetail;
  onUpdate: (value: TechnicianDetail) => void;
  onMissing?: () => void;
}) {
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const calendars = useResource<Calendar[]>("/calendars");
  const [saving, setSaving] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setSaving(true);
    setError("");
    setSaved(false);
    const form = new FormData(event.currentTarget);
    const payload: TechnicianUpdate = {
      expected_record_version: t.record_version,
      first_name: String(form.get("first_name")).trim(),
      last_name: String(form.get("last_name")).trim(),
      status: form.get("status") as "ACTIVE" | "INACTIVE",
      accounting_timezone:
        String(form.get("accounting_timezone") ?? "").trim() || null,
    };
    try {
      onUpdate(
        await api<TechnicianDetail>(`/technicians/${t.id}`, {
          method: "PATCH",
          body: json(payload),
        }),
      );
      setSaved(true);
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }
  async function assign(id: string) {
    if (pending.current) return;
    pending.current = true;
    setAssigning(true);
    setError("");
    try {
      await api(
        `/technicians/${t.id}/calendar`,
        id
          ? { method: "PUT", body: json({ calendar_id: id }) }
          : { method: "DELETE" },
      );
    } catch (error) {
      if (mounted.current) setError(errorMessage(error));
    } finally {
      // A conflict can mean the calendar was excluded or the technician deleted.
      // Always recover server truth, including when the write response was lost.
      try {
        const fresh = await api<TechnicianDetail>(`/technicians/${t.id}`);
        if (mounted.current) onUpdate(fresh);
      } catch (error) {
        if (mounted.current) {
          setError(errorMessage(error));
          if (error instanceof ApiError && error.status === 404) onMissing?.();
        }
      }
      pending.current = false;
      if (mounted.current) {
        calendars.reload();
        setAssigning(false);
      }
    }
  }
  return (
    <section className="panel profile-panel">
      <div className="panel-heading">
        <h2>
          <UserRound size={18} />
          Profile & Connections
        </h2>
        <span className="micro-label">01</span>
      </div>
      <div className="panel-body">
        <form onSubmit={save} onChange={() => setSaved(false)}>
          <fieldset disabled={saving || assigning}>
            <div className="form-grid">
              <label>
                First name
                <input
                  name="first_name"
                  required
                  maxLength={100}
                  defaultValue={t.first_name}
                />
              </label>
              <label>
                Last name
                <input
                  name="last_name"
                  required
                  maxLength={100}
                  defaultValue={t.last_name}
                />
              </label>
            </div>
            <AccountingTimezone
              key={`${t.id}:${t.accounting_timezone}`}
              value={t.accounting_timezone}
            />
            <p className="field-hint">
              Set the technician’s IANA timezone to enable expenses. No calendar
              or browser timezone is assumed.
            </p>
            <div className="profile-form-footer">
              <label>
                Status
                <select name="status" defaultValue={t.status}>
                  <option value="ACTIVE">Active</option>
                  <option value="INACTIVE">Inactive</option>
                </select>
              </label>
              <button
                className="button secondary"
                disabled={saving || assigning}
              >
                {saved ? <Check size={16} /> : <Save size={16} />}
                {saving ? "Saving…" : saved ? "Saved" : "Save profile"}
              </button>
            </div>
            {saved && (
              <span role="status" className="save-notice">
                Profile saved.
              </span>
            )}
          </fieldset>
        </form>
        <ErrorNotice message={error} />
        <div className="connection-section">
          <h3>
            <Link2 size={15} />
            CALENDAR
          </h3>
          <label>
            Assigned calendar
            <select
              id="profile-calendar"
              aria-label="Assigned calendar"
              value={t.calendar?.id ?? ""}
              disabled={assigning || saving || !calendars.data}
              onChange={(event) => void assign(event.target.value)}
            >
              <option value="">Not assigned</option>
              {calendars.data
                ?.filter(
                  (c) =>
                    !c.excluded_at &&
                    ((c.availability !== "UNAVAILABLE" &&
                      (!c.assigned_technician ||
                        c.assigned_technician.id === t.id)) ||
                      c.id === t.calendar?.id),
                )
                .map((c) => (
                  <option
                    key={c.id}
                    value={c.id}
                    disabled={c.availability === "UNAVAILABLE"}
                  >
                    {c.name}
                  </option>
                ))}
            </select>
          </label>
          <p className="field-hint" role="status">
            {assigning
              ? "Saving assignment…"
              : "Calendar selection saves automatically."}
          </p>
          {t.calendar?.availability === "UNAVAILABLE" && (
            <p className="calendar-warning" role="status">
              Calendar unavailable in connected Google account.
            </p>
          )}
          <ErrorNotice message={calendars.error} retry={calendars.reload} />
        </div>
        <TelegramConnections
          technicianId={t.id}
          technicianName={`${t.first_name} ${t.last_name}`}
          active={t.status === "ACTIVE"}
        />
        <div className="connection-section">
          <h3>GPS TRACKING</h3>
          <div className="connection-row">
            <span>
              <MapPin size={16} />
              Provider
            </span>
            <span className="muted">
              {t.integrations.gps_provider === "NONE"
                ? "Not configured"
                : "Moto Watchdog Share"}
            </span>
          </div>
          <DisabledAction reason="GPS integration will be added in a later stage.">
            Configure GPS
          </DisabledAction>
        </div>
      </div>
    </section>
  );
}
