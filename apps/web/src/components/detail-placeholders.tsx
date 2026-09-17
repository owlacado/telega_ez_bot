import {
  CalendarDays,
  ChartNoAxesCombined,
  MapPin,
  ReceiptText,
  Route,
} from "lucide-react";
import type { TechnicianDetail, LocationState } from "@hub/contracts";
import { EmptyState } from "./ui";
// Reserved states describe evidence available from a future GPS adapter.
export const locationStateLabels: Record<LocationState, string> = {
  ACTIVE_TRIP: "Active trip",
  LAST_KNOWN_STOP: "Last known stop",
  NO_DATA: "No data",
  UNKNOWN: "Unknown",
};
export function AccountingPanel() {
  return (
    <section className="panel placeholder-panel">
      <div className="panel-heading">
        <h2>
          <ReceiptText size={18} />
          Accounting
        </h2>
        <span className="micro-label">02</span>
      </div>
      <EmptyState
        icon={<ChartNoAxesCombined size={28} />}
        title="No accounting source connected."
      >
        <p>A clear picture of the work behind the numbers.</p>
      </EmptyState>
      <div className="future-data">
        <span className="micro-label">WHEN CONNECTED</span>
        <div>
          <span>Today’s revenue & expenses</span>
          <span>Weekly revenue & expenses</span>
          <span>Jobs & payment breakdown</span>
        </div>
      </div>
      <div className="panel-footer">
        Accounting connections are planned for a later stage.
      </div>
    </section>
  );
}
export function JobsPanel({ technician }: { technician: TechnicianDetail }) {
  return (
    <section className="panel placeholder-panel">
      <div className="panel-heading">
        <h2>
          <CalendarDays size={18} />
          Today’s Jobs
        </h2>
        <span className="micro-label">03</span>
      </div>
      <EmptyState
        icon={<CalendarDays size={28} />}
        title="No calendar synchronization configured."
      >
        <p>Scheduled work will appear here when your calendar is connected.</p>
      </EmptyState>
      <div className="assigned-calendar">
        <CalendarDays size={19} />
        <div>
          <span className="micro-label">ASSIGNED CALENDAR</span>
          <strong>{technician.calendar?.name ?? "Not assigned"}</strong>
        </div>
      </div>
      <div className="panel-footer">
        Google Calendar synchronization will be added in a later stage.
      </div>
    </section>
  );
}
export function GpsPanel() {
  return (
    <section className="panel placeholder-panel gps-panel">
      <div className="panel-heading">
        <h2>
          <MapPin size={18} />
          Vehicle Location
        </h2>
        <span className="micro-label">04</span>
      </div>
      <div className="map-placeholder" aria-hidden="true">
        <div className="map-road road-one" />
        <div className="map-road road-two" />
        <div className="map-road road-three" />
        <div className="map-pin">
          <Route size={23} />
        </div>
      </div>
      <div className="gps-empty">
        <h3>GPS tracking is not configured.</h3>
        <p className="muted">
          Location information will appear once a provider is connected.
        </p>
        <span className="stage-badge">NO PROVIDER CONNECTED</span>
      </div>
      <div className="panel-footer">No location data is being collected.</div>
    </section>
  );
}
