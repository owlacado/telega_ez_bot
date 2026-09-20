"use client";

import { Activity, Database, RefreshCw } from "lucide-react";
import type { OperationsHealth } from "@hub/contracts";
import { useResource } from "@/lib/use-resource";
import { ErrorNotice, Loading } from "./ui";

export function OperationsHealthPanel() {
  const health = useResource<OperationsHealth>("/operations/health");
  if (!health.data) {
    return (
      <section
        className="panel operations-panel"
        aria-label="Operations health"
      >
        <div className="panel-heading">
          <h2>
            <Activity size={18} /> Operations Health
          </h2>
        </div>
        <ErrorNotice message={health.error} retry={health.reload} />
        {!health.error && <Loading />}
      </section>
    );
  }
  const components = [
    ["Database", health.data.database],
    ["Migration", health.data.migration],
    ["Telegram worker", health.data.telegram_worker],
    ["Schedule worker", health.data.schedule_worker],
    ["Mirror worker", health.data.mirror_worker],
    ["Google configuration", health.data.google_configuration],
  ] as const;
  return (
    <section className="panel operations-panel" aria-label="Operations health">
      <div className="panel-heading">
        <div>
          <h2>
            <Activity size={18} /> Operations Health
          </h2>
          <p className="muted">
            Release {health.data.app_version} ·{" "}
            {health.data.release_commit.slice(0, 12)}
          </p>
        </div>
        <button
          className="button secondary"
          type="button"
          onClick={health.reload}
          aria-label="Refresh operations health"
        >
          <RefreshCw size={15} /> Refresh
        </button>
      </div>
      <div className="operations-grid">
        {components.map(([label, component]) => (
          <div className="operation-status" key={label}>
            <Database size={16} />
            <span>
              <strong>{label}</strong>
              <small>{component.message}</small>
            </span>
            <b>{component.state}</b>
          </div>
        ))}
      </div>
    </section>
  );
}
