import { CircleCheck, CircleDot, CircleX } from "lucide-react";
import type { Technician } from "@hub/contracts";

type Readiness = Technician["pilot_readiness"];

export function ReadinessBadge({ readiness }: { readiness: Readiness }) {
  return (
    <span
      className={`readiness-badge ${readiness.ready ? "ready" : "needs-action"}`}
      aria-label={
        readiness.ready
          ? "Ready for Pilot"
          : `Needs Setup: ${readiness.blocking_count}`
      }
    >
      {readiness.ready ? <CircleCheck size={13} /> : <CircleDot size={13} />}
      {readiness.ready
        ? "Ready for Pilot"
        : `Needs Setup (${readiness.blocking_count})`}
    </span>
  );
}

export function PilotReadiness({ readiness }: { readiness: Readiness }) {
  return (
    <section className="panel readiness-panel" aria-label="Pilot readiness">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">PILOT READINESS</span>
          <h2>{readiness.ready ? "Ready for Pilot" : "Needs Setup"}</h2>
          <p className="muted">
            Backend-verified requirements for current pilot workflows.
          </p>
        </div>
        <ReadinessBadge readiness={readiness} />
      </div>
      <div className="readiness-list">
        {readiness.requirements.map((requirement) => {
          const ready = requirement.status === "READY";
          const optional = requirement.status === "OPTIONAL";
          const Icon = ready ? CircleCheck : optional ? CircleDot : CircleX;
          return (
            <div className="readiness-row" key={requirement.key}>
              <Icon size={17} aria-hidden="true" />
              <div>
                <strong>{requirement.label}</strong>
                <span>{requirement.reason}</span>
                {requirement.action && <small>{requirement.action}</small>}
              </div>
              <b>{requirement.status.replace("_", " ")}</b>
            </div>
          );
        })}
      </div>
    </section>
  );
}
