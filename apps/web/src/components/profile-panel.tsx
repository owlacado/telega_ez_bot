"use client";
import { useState, type FormEvent } from "react";
import {
  Check,
  Link2,
  MapPin,
  MessageCircle,
  Save,
  UsersRound,
  UserRound,
} from "lucide-react";
import type {
  Calendar,
  TechnicianDetail,
  TechnicianUpdate,
} from "@hub/contracts";
import { api, errorMessage, json } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { DisabledAction, ErrorNotice, Status } from "./ui";
export function ProfilePanel({
  technician: t,
  onUpdate,
}: {
  technician: TechnicianDetail;
  onUpdate: (value: TechnicianDetail) => void;
}) {
  const calendars = useResource<Calendar[]>("/calendars");
  const [saving, setSaving] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSaved(false);
    const form = new FormData(event.currentTarget);
    const payload: TechnicianUpdate = {
      first_name: String(form.get("first_name")).trim(),
      last_name: String(form.get("last_name")).trim(),
      photo_url: String(form.get("photo_url")).trim() || null,
      status: form.get("status") as "ACTIVE" | "INACTIVE",
      driver_license_id: String(form.get("driver_license_id")).trim() || null,
      ssn_last4: String(form.get("ssn_last4")).trim() || null,
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
      setSaving(false);
    }
  }
  async function assign(id: string) {
    setAssigning(true);
    setError("");
    try {
      await api(
        `/technicians/${t.id}/calendar`,
        id
          ? { method: "PUT", body: json({ calendar_id: id }) }
          : { method: "DELETE" },
      );
      onUpdate(await api<TechnicianDetail>(`/technicians/${t.id}`));
      calendars.reload();
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setAssigning(false);
    }
  }
  const telegramReason =
    "Telegram integration will be added in the next stage.";
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
          <label>
            Photo URL
            <input
              name="photo_url"
              type="url"
              maxLength={2048}
              defaultValue={t.photo_url ?? ""}
              placeholder="https://…"
            />
          </label>
          <div className="form-grid">
            <label>
              Driver License ID
              <input
                name="driver_license_id"
                maxLength={100}
                defaultValue={t.driver_license_id ?? ""}
                autoComplete="off"
                placeholder="Optional"
              />
            </label>
            <label>
              SSN last 4
              <input
                name="ssn_last4"
                type="password"
                inputMode="numeric"
                pattern="[0-9]{4}"
                minLength={4}
                maxLength={4}
                defaultValue={t.ssn_last4 ?? ""}
                autoComplete="new-password"
                placeholder="Optional"
              />
            </label>
          </div>
          <p className="field-hint sensitive-hint">
            Only the final 4 digits. Never enter a full SSN.
          </p>
          <div className="profile-form-footer">
            <label>
              Status
              <select name="status" defaultValue={t.status}>
                <option value="ACTIVE">Active</option>
                <option value="INACTIVE">Inactive</option>
              </select>
            </label>
            <button className="button secondary" disabled={saving || assigning}>
              {saved ? <Check size={16} /> : <Save size={16} />}
              {saving ? "Saving…" : saved ? "Saved" : "Save profile"}
            </button>
          </div>
          {saved && (
            <span role="status" className="save-notice">
              Profile saved.
            </span>
          )}
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
              aria-label="Assigned calendar"
              value={t.calendar?.id ?? ""}
              disabled={assigning || saving || !calendars.data}
              onChange={(event) => void assign(event.target.value)}
            >
              <option value="">Not assigned</option>
              {calendars.data
                ?.filter(
                  (c) =>
                    !c.assigned_technician || c.assigned_technician.id === t.id,
                )
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
          </label>
          <p className="field-hint" role="status">
            {assigning
              ? "Saving assignment…"
              : "Calendar selection saves automatically. Synchronization is not connected."}
          </p>
          <ErrorNotice message={calendars.error} retry={calendars.reload} />
        </div>
        <div className="connection-section">
          <h3>TELEGRAM</h3>
          <div className="connection-row">
            <span>
              <MessageCircle size={16} />
              Private bot
            </span>
            <Status value={t.integrations.telegram_private} />
          </div>
          <div className="connection-row">
            <span>
              <UsersRound size={16} />
              Work group
            </span>
            <Status value={t.integrations.telegram_group} />
          </div>
          <div className="connection-actions">
            <DisabledAction reason={telegramReason}>
              Connect Telegram
            </DisabledAction>
            <DisabledAction reason={telegramReason}>
              Connect Work Group
            </DisabledAction>
          </div>
        </div>
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
