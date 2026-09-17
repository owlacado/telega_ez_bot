"use client";
import { useState } from "react";
import Link from "next/link";
import { CalendarDays, RefreshCw, Trash2 } from "lucide-react";
import type { Calendar } from "@hub/contracts";
import { api, errorMessage, json } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import {
  DisabledAction,
  EmptyState,
  ErrorNotice,
  Loading,
} from "@/components/ui";
import { Modal } from "@/components/modal";
export default function CalendarsPage() {
  const { data, error, reload } = useResource<Calendar[]>("/calendars");
  const [removing, setRemoving] = useState<Calendar | null>(null);
  const [busy, setBusy] = useState(false);
  const [removeError, setRemoveError] = useState("");
  async function remove() {
    if (!removing || busy) return;
    setBusy(true);
    setRemoveError("");
    try {
      await api(`/calendars/${removing.id}`, {
        method: "DELETE",
        body: json({
          confirmation: "DELETE",
          detach_assigned: Boolean(removing.assigned_technician),
        }),
      });
      setRemoving(null);
      reload();
    } catch (error) {
      setRemoveError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">TEAM CONNECTIONS</div>
          <h1>Calendars</h1>
          <p className="muted">
            Keep every local calendar connected to the right person.
          </p>
        </div>
        <DisabledAction reason="Google Calendar connection has not been configured.">
          <RefreshCw size={16} />
          Scan Google Calendars
        </DisabledAction>
      </div>
      <div className="info-banner">
        <CalendarDays size={20} />
        <div>
          <strong>Your local calendar directory</strong>
          <p>
            These records live in Technician Hub. Google Calendar
            synchronization is not connected.
          </p>
        </div>
      </div>
      <ErrorNotice message={error} retry={reload} />
      {!data && !error ? (
        <Loading />
      ) : data?.length ? (
        <section className="panel table-panel">
          <div className="panel-heading">
            <h2>
              All calendars <span className="count-pill">{data.length}</span>
            </h2>
            <span className="muted">
              {data.filter((c) => !c.assigned_technician).length} available
            </span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Calendar</th>
                  <th>Assigned Technician</th>
                  <th>Status</th>
                  <th className="align-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.map((calendar) => (
                  <tr key={calendar.id}>
                    <td>
                      <div className="calendar-name">
                        <span className="calendar-icon">
                          <CalendarDays size={18} />
                        </span>
                        <strong>{calendar.name}</strong>
                      </div>
                    </td>
                    <td>
                      {calendar.assigned_technician ? (
                        <Link
                          className="text-link"
                          href={`/technicians/${calendar.assigned_technician.id}`}
                        >
                          {calendar.assigned_technician.name}
                        </Link>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <span
                        className={`status ${calendar.assigned_technician ? "status-green" : "status-neutral"}`}
                      >
                        <i />
                        {calendar.assigned_technician
                          ? "Assigned"
                          : "Available"}
                      </span>
                    </td>
                    <td className="align-right">
                      <button
                        className="icon-button remove-calendar"
                        aria-label={`Remove ${calendar.name}`}
                        title="Remove local calendar"
                        onClick={() => {
                          setRemoveError("");
                          setRemoving(calendar);
                        }}
                      >
                        <Trash2 size={17} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        data && (
          <div className="panel">
            <EmptyState
              icon={<CalendarDays size={27} />}
              title="No local calendars yet"
            >
              <p>
                Development calendars can be added with the seed command in the
                project README.
              </p>
              <p>
                Google Calendar scanning will be available once a connection is
                configured.
              </p>
            </EmptyState>
          </div>
        )
      )}
      <p className="page-footnote">
        Removing a calendar here only removes the local record. It never deletes
        anything from Google.
      </p>
      {removing && (
        <Modal
          title="Remove local calendar?"
          onClose={() => setRemoving(null)}
          busy={busy}
        >
          <p className="modal-description">
            Remove <strong>{removing.name}</strong> from the Technician Hub
            database?
          </p>
          {removing.assigned_technician && (
            <div className="error-notice">
              <span>
                <strong>{removing.assigned_technician.name}</strong> will become
                unassigned. Their technician profile will remain.
              </span>
            </div>
          )}
          <p className="muted">Nothing will be deleted from Google Calendar.</p>
          <ErrorNotice message={removeError} />
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => setRemoving(null)}
              disabled={busy}
            >
              Cancel
            </button>
            <button className="button danger" onClick={remove} disabled={busy}>
              {busy ? "Removing…" : "Remove calendar"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
