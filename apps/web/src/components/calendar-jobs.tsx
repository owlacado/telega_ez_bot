"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { CalendarDays } from "lucide-react";
import type { ScheduleRead } from "@hub/contracts";
import { useSchedule } from "@/lib/use-schedule";
import { Modal } from "./modal";
import { Loading } from "./ui";
import { ScheduleDelivery } from "./schedule-delivery";

export function previewLabel(today?: string | null, target?: string | null) {
  if (!today || !target) return "Preview Next Work Day Schedule";
  // Date-only strings are calendar labels, never browser-local instants.
  const weekday = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    timeZone: "UTC",
  }).format(new Date(`${target}T12:00:00Z`));
  return `Preview ${weekday}’s Schedule`;
}
export function operationalDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}
const states: Record<string, [string, string, string]> = {
  NO_CALENDAR: [
    "No calendar assigned.",
    "Assign Calendar",
    "#profile-calendar",
  ],
  CALENDAR_UNAVAILABLE: [
    "Assigned calendar unavailable.",
    "Manage Calendars",
    "/calendars",
  ],
  EVENT_SCOPE_REQUIRED: [
    "Google Calendar event access is required.",
    "Grant Event Access",
    "/calendars",
  ],
  REAUTH_REQUIRED: [
    "Google Calendar connection needs attention.",
    "Reconnect",
    "/calendars",
  ],
  TIMEZONE_REQUIRED: [
    "Calendar timezone is unavailable. Refresh calendar discovery.",
    "Manage Calendars",
    "/calendars",
  ],
};
export function ScheduleContent({
  data,
  error,
  loading,
  refresh,
  preview = false,
}: ReturnType<typeof useSchedule> & { preview?: boolean }) {
  if (loading) return <Loading />;
  if (error)
    return (
      <div role="alert">
        <p>Unable to refresh calendar right now.</p>
        <button className="button secondary" onClick={refresh}>
          Retry
        </button>
      </div>
    );
  if (!data) return null;
  const state = states[data.state];
  if (state)
    return (
      <div className="schedule-empty">
        <p>{state[0]}</p>
        <Link className="button secondary" href={state[2]}>
          {state[1]}
        </Link>
      </div>
    );
  if (data.state !== "READY")
    return (
      <div role="alert">
        <p>
          {data.state === "CHANGED"
            ? "Calendar assignment or connection changed. Refresh to load the current schedule."
            : data.state === "BUSY"
              ? "A schedule refresh is already running."
              : "Unable to refresh calendar right now."}
        </p>
        {data.retry_at && (
          <p>Retry after {new Date(data.retry_at).toISOString()}</p>
        )}
        <button className="button secondary" onClick={refresh}>
          Retry
        </button>
      </div>
    );
  return (
    <>
      <div className="schedule-meta">
        <strong>{data.calendar?.name}</strong>
        <span>
          {data.operational_date && operationalDate(data.operational_date)}
        </span>
        <small>Calendar time · {data.timezone}</small>
      </div>
      {(data.warnings ?? []).map((w) => (
        <p role="status" key={w}>
          {w}
        </p>
      ))}
      {!(data.jobs ?? []).length ? (
        <p className="schedule-empty">
          {preview ? "No scheduled jobs." : "No scheduled jobs today."}
        </p>
      ) : (
        <ol className="schedule-jobs">
          {(data.jobs ?? []).map((job) => (
            <li key={job.provider_event_id}>
              <time dateTime={job.start}>{job.display_start_time}</time>
              <div>
                <strong>{preview ? job.schedule_summary : job.summary}</strong>
                {job.location && <p>{job.location}</p>}
                {!preview && job.description && (
                  <details>
                    <summary>Job notes</summary>
                    <p>{job.description}</p>
                  </details>
                )}
                {job.html_link && (
                  <a
                    href={job.html_link}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open in Google Calendar
                  </a>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
      <div className="field-hint">
        {(data.jobs ?? []).length}{" "}
        {(data.jobs ?? []).length === 1 ? "job" : "jobs"}
        {data.last_fetched_at && (
          <> · Last refreshed {new Date(data.last_fetched_at).toISOString()}</>
        )}
      </div>
    </>
  );
}
export function TodayJobs({
  resource,
}: {
  resource: ReturnType<typeof useSchedule>;
}) {
  return (
    <section className="panel" aria-label="Today's Jobs">
      <div className="panel-heading">
        <h2>
          <CalendarDays size={18} />
          Today’s Jobs
        </h2>
        <button
          className="button secondary"
          disabled={resource.loading}
          onClick={resource.refresh}
        >
          Refresh
        </button>
      </div>
      <div className="panel-body">
        <ScheduleContent {...resource} />
      </div>
    </section>
  );
}
function Preview({ id, onClose }: { id: string; onClose: () => void }) {
  const resource = useSchedule(`/technicians/${id}/calendar/next-schedule`);
  return (
    <Modal title="Next Work Day Schedule Preview" onClose={onClose}>
      <div className="panel-body">
        {resource.data && (
          <h3>
            {resource.data.technician.first_name}{" "}
            {resource.data.technician.last_name}
          </h3>
        )}
        <ScheduleContent {...resource} preview />
        <ScheduleDelivery
          id={id}
          schedule={resource.data}
          refresh={resource.refresh}
        />
        <button className="button secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}
export function PreviewSchedule({
  id,
  today,
}: {
  id: string;
  today: ScheduleRead | null;
}) {
  const [open, setOpen] = useState(false);
  const opened = useRef(false);
  return (
    <>
      <button
        className="button secondary"
        onClick={() => {
          if (!opened.current) {
            opened.current = true;
            setOpen(true);
          }
        }}
      >
        <CalendarDays size={16} />
        {previewLabel(today?.operational_date, today?.next_schedule_date)}
      </button>
      {open && (
        <Preview
          key={id}
          id={id}
          onClose={() => {
            opened.current = false;
            setOpen(false);
          }}
        />
      )}
    </>
  );
}
