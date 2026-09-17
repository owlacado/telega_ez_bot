"use client";
import { Suspense, useRef, useState } from "react";
import Link from "next/link";
import { CalendarDays, Trash2 } from "lucide-react";
import type { Calendar, Technician } from "@hub/contracts";
import { api, errorMessage, json } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { EmptyState, ErrorNotice, Loading } from "@/components/ui";
import { Modal } from "@/components/modal";
import { GoogleCalendarConnection } from "@/components/google-calendar-connection";

export default function CalendarsPage() {
  const { data, error, reload } = useResource<Calendar[]>("/calendars");
  const technicians = useResource<Technician[]>("/technicians");
  const [removing, setRemoving] = useState<Calendar | null>(null);
  const [assigning, setAssigning] = useState<Calendar | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [failure, setFailure] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("All");
  const [showExcluded, setShowExcluded] = useState(false);
  const excluded = data?.filter((c) => c.excluded_at) ?? [];
  const visible = data?.filter(
    (c) =>
      !c.excluded_at &&
      c.name.toLowerCase().includes(search.toLowerCase()) &&
      (filter === "All" ||
        (filter === "Assigned" && c.assigned_technician) ||
        (filter === "Available" &&
          c.availability !== "UNAVAILABLE" &&
          !c.assigned_technician) ||
        (filter === "Unavailable" && c.availability === "UNAVAILABLE")),
  );
  async function mutate(path: string, method: string, body?: object) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setFailure("");
    try {
      await api(path, { method, ...(body ? { body: json(body) } : {}) });
      setRemoving(null);
      setAssigning(null);
      reload();
      technicians.reload();
    } catch (error) {
      setFailure(errorMessage(error));
      reload();
      technicians.reload();
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  function remove() {
    if (!removing) return;
    void mutate(
      `/calendars/${removing.id}${removing.source === "GOOGLE" ? "/exclude" : ""}`,
      removing.source === "GOOGLE" ? "POST" : "DELETE",
      removing.source === "GOOGLE"
        ? {
            confirmation: "EXCLUDE",
            expected_assigned_technician_id:
              removing.assigned_technician?.id ?? null,
          }
        : {
            confirmation: "DELETE",
            detach_assigned: Boolean(removing.assigned_technician),
          },
    );
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">TEAM CONNECTIONS</div>
          <h1>Calendars</h1>
          <p className="muted">
            Connect each discovered calendar to the right technician.
          </p>
        </div>
      </div>
      <Suspense fallback={<Loading />}>
        <GoogleCalendarConnection onChange={reload} />
      </Suspense>
      <ErrorNotice message={error} retry={reload} />
      {!removing && !assigning && <ErrorNotice message={failure} />}
      <div className="calendar-toolbar">
        <label>
          Search calendars
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Find a calendar..."
          />
        </label>
        <label>
          Filter
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            {["All", "Assigned", "Available", "Unavailable"].map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </label>
      </div>
      {!data && !error ? (
        <Loading />
      ) : visible?.length ? (
        <section className="panel table-panel">
          <div className="panel-heading">
            <h2>
              All calendars <span className="count-pill">{visible.length}</span>
            </h2>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Calendar</th>
                  <th>Assigned Technician</th>
                  <th>Provider Status</th>
                  <th className="align-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((calendar) => (
                  <tr key={calendar.id}>
                    <td>
                      <div className="calendar-name">
                        <span className="calendar-icon">
                          <CalendarDays size={18} />
                        </span>
                        <div>
                          <strong title={calendar.name}>{calendar.name}</strong>
                          <small className="muted">
                            {calendar.source === "GOOGLE"
                              ? "Google"
                              : "Local demo"}
                          </small>
                        </div>
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
                        <span className="muted">Unassigned</span>
                      )}
                    </td>
                    <td>
                      <span
                        className={`status ${calendar.availability === "UNAVAILABLE" ? "status-neutral" : "status-green"}`}
                      >
                        <i />
                        {calendar.availability === "UNAVAILABLE"
                          ? "Unavailable"
                          : "Available"}
                      </span>
                      {calendar.assigned_technician && (
                        <small className="muted">Assigned</small>
                      )}
                    </td>
                    <td className="align-right">
                      <div className="calendar-row-actions">
                        <button
                          className="button secondary"
                          disabled={
                            busy ||
                            (calendar.availability === "UNAVAILABLE" &&
                              !calendar.assigned_technician)
                          }
                          onClick={() => {
                            setFailure("");
                            setSelected(calendar.assigned_technician?.id ?? "");
                            setAssigning(calendar);
                          }}
                        >
                          {calendar.assigned_technician
                            ? "Change assignment"
                            : "Assign"}
                        </button>
                        <button
                          className="icon-button remove-calendar"
                          disabled={busy}
                          aria-label={`Remove ${calendar.name}`}
                          title={
                            calendar.source === "GOOGLE"
                              ? "Remove from Technician Hub"
                              : "Remove local calendar"
                          }
                          onClick={() => {
                            setFailure("");
                            setRemoving(calendar);
                          }}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
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
              title="No calendars to show"
            >
              <p>
                Connect Google Calendar and scan, or adjust your search and
                filter.
              </p>
            </EmptyState>
          </div>
        )
      )}
      <button
        className="button secondary excluded-toggle"
        onClick={() => setShowExcluded(!showExcluded)}
      >
        Excluded Calendars ({excluded.length})
      </button>
      {showExcluded && (
        <section className="panel" aria-label="Excluded Calendars">
          {excluded.length ? (
            excluded.map((c) => (
              <div className="excluded-row" key={c.id}>
                <span>{c.name}</span>
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() =>
                    void mutate(`/calendars/${c.id}/restore`, "POST")
                  }
                >
                  Restore {c.name}
                </button>
              </div>
            ))
          ) : (
            <p className="muted">No excluded calendars.</p>
          )}
        </section>
      )}
      <p className="page-footnote">
        Removing a Google calendar from Technician Hub keeps it excluded until
        you restore it. The Google Calendar itself is never deleted.
      </p>
      {removing && (
        <Modal
          title={
            removing.source === "GOOGLE"
              ? "Remove from Technician Hub?"
              : "Remove local calendar?"
          }
          onClose={() => setRemoving(null)}
          busy={busy}
        >
          <p className="modal-description">
            Remove <strong>{removing.name}</strong> from Technician Hub?
          </p>
          {removing.assigned_technician && (
            <div className="error-notice">
              <span>
                <strong>{removing.assigned_technician.name}</strong> will become
                unassigned. Their technician profile and assignment history will
                remain.
              </span>
            </div>
          )}
          <p className="muted">Nothing will be deleted from Google Calendar.</p>
          <ErrorNotice message={failure} />
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => setRemoving(null)}
              disabled={busy}
            >
              Cancel
            </button>
            <button className="button danger" onClick={remove} disabled={busy}>
              {busy ? "Removing..." : "Remove calendar"}
            </button>
          </div>
        </Modal>
      )}
      {assigning && (
        <Modal
          title={`Assignment - ${assigning.name}`}
          onClose={() => setAssigning(null)}
          busy={busy}
        >
          <label>
            Assigned technician
            <select
              aria-label="Assigned technician"
              value={selected}
              disabled={busy || !technicians.data}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">Not assigned</option>
              {technicians.data?.map((t) => (
                <option
                  key={t.id}
                  value={t.id}
                  disabled={assigning.availability === "UNAVAILABLE"}
                >
                  {t.first_name} {t.last_name}
                </option>
              ))}
            </select>
          </label>
          {selected &&
            technicians.data?.find((t) => t.id === selected)?.calendar && (
              <p className="field-hint">
                The previous calendar assignment for this technician will be
                replaced.
              </p>
            )}
          {assigning.availability === "UNAVAILABLE" && (
            <p className="field-hint">
              This calendar is unavailable. You can remove its assignment.
            </p>
          )}
          <ErrorNotice message={technicians.error} retry={technicians.reload} />
          <ErrorNotice message={failure} />
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setAssigning(null)}
            >
              Cancel
            </button>
            <button
              className="button primary"
              disabled={
                busy ||
                !technicians.data ||
                (assigning.availability === "UNAVAILABLE" && !!selected)
              }
              onClick={() =>
                void mutate(`/calendars/${assigning.id}/assignment`, "PUT", {
                  technician_id: selected || null,
                  expected_assigned_technician_id:
                    assigning.assigned_technician?.id ?? null,
                })
              }
            >
              {busy ? "Saving..." : "Save assignment"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
