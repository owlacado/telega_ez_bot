"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Trash2 } from "lucide-react";
import type { TechnicianDetail } from "@hub/contracts";
import { api, errorMessage, json } from "@/lib/api";
import { Modal } from "./modal";
import { ErrorNotice } from "./ui";
type DeleteProps = { technician: TechnicianDetail; onClose: () => void };
export function DeleteTechnician(props: DeleteProps) {
  return (
    <DeleteConfirmation
      key={`${props.technician.id}:${props.technician.updated_at}`}
      {...props}
    />
  );
}
function DeleteConfirmation({
  technician,
  onClose,
}: {
  technician: TechnicianDetail;
  onClose: () => void;
}) {
  const router = useRouter();
  const pending = useRef(false);
  const [remaining, setRemaining] = useState(10);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const name = `${technician.first_name} ${technician.last_name}`;
  const expected = `DELETE ${name}`;
  useEffect(() => {
    const deadline = Date.now() + 10_000;
    const timer = setInterval(
      () =>
        setRemaining(Math.max(0, Math.ceil((deadline - Date.now()) / 1000))),
      200,
    );
    return () => clearInterval(timer);
  }, []);
  const ready = remaining === 0 && typed === expected && !busy;
  async function remove() {
    if (!ready || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await api(`/technicians/${technician.id}`, {
        method: "DELETE",
        body: json({
          confirmation: "DELETE",
          expected_updated_at: technician.updated_at,
        }),
      });
      router.push("/technicians");
    } catch (error) {
      setError(errorMessage(error));
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <Modal title="Permanently delete technician?" onClose={onClose} busy={busy}>
      <div className="delete-identity">
        <AlertTriangle size={25} />
        <strong>{name}</strong>
      </div>
      <p className="modal-description">
        This permanently removes the technician profile, sensitive profile
        fields, assignment history, and integration bindings from Technician
        Hub. Local calendars remain available. Nothing is deleted from external
        providers. Pending Telegram invitations and notifications are removed.
        Already delivered messages are not erased.
      </p>
      <p className="warning-text">This action cannot be undone.</p>
      <label>
        Type <strong>{expected}</strong> to confirm
        <input
          aria-label="Deletion confirmation"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      </label>
      <p className="field-hint">
        The final action unlocks after 10 seconds and an exact confirmation.
      </p>
      <ErrorNotice message={error} />
      <div className="modal-actions">
        <button className="button secondary" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button className="button danger" onClick={remove} disabled={!ready}>
          <Trash2 size={16} />
          {busy
            ? "Deleting…"
            : remaining > 0
              ? `Delete permanently (${remaining})`
              : "DELETE PERMANENTLY"}
        </button>
      </div>
    </Modal>
  );
}
