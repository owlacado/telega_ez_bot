"use client";
import { useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, UserRoundPlus } from "lucide-react";
import type {
  Calendar,
  TechnicianDetail,
  TechnicianCreate,
} from "@hub/contracts";
import { api, errorMessage, json } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { Modal } from "./modal";
import { ErrorNotice } from "./ui";
export function AddTechnician({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const pending = useRef(false);
  const calendars = useResource<Calendar[]>("/calendars");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const payload: TechnicianCreate = {
      first_name: String(form.get("first_name")).trim(),
      last_name: String(form.get("last_name")).trim(),
      photo_url: String(form.get("photo_url")).trim() || null,
      calendar_id: String(form.get("calendar_id")) || null,
    };
    try {
      const technician = await api<TechnicianDetail>("/technicians", {
        method: "POST",
        body: json(payload),
      });
      router.push(`/technicians/${technician.id}`);
    } catch (error) {
      setError(errorMessage(error));
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <Modal title="Add Technician" onClose={onClose} busy={busy}>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <div className="modal-intro">
            <span className="empty-icon small">
              <UserRoundPlus size={22} />
            </span>
            <p>
              Start with a name. Connections and profile details can be added
              later.
            </p>
          </div>
          <ErrorNotice message={error} />
          <div className="form-grid">
            <label>
              First name
              <input
                name="first_name"
                required
                maxLength={100}
                autoComplete="given-name"
                autoFocus
              />
            </label>
            <label>
              Last name
              <input
                name="last_name"
                required
                maxLength={100}
                autoComplete="family-name"
              />
            </label>
          </div>
          <label>
            Photo URL <span className="optional">Optional</span>
            <input
              name="photo_url"
              type="url"
              maxLength={2048}
              placeholder="https://…"
            />
          </label>
          <label>
            Calendar <span className="optional">Optional</span>
            <select
              name="calendar_id"
              defaultValue=""
              disabled={!calendars.data}
            >
              <option value="">Assign later</option>
              {calendars.data
                ?.filter(
                  (c) =>
                    !c.assigned_technician &&
                    !c.excluded_at &&
                    c.availability === "AVAILABLE",
                )
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
          </label>
          <ErrorNotice message={calendars.error} retry={calendars.reload} />
          <p className="field-hint">
            Telegram and GPS connections are not required.
          </p>
          <div className="modal-actions">
            <button
              type="button"
              className="button secondary"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
            <button className="button primary" disabled={busy}>
              {busy ? "Creating…" : "Create Technician"}
              <ArrowRight size={16} />
            </button>
          </div>
        </fieldset>
      </form>
    </Modal>
  );
}
