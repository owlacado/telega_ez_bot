"use client";
import { useState } from "react";
import type { WorkReport, WorkReportList } from "@hub/contracts";
import { useResource } from "@/lib/use-resource";
import { ErrorNotice, Loading } from "./ui";
import { Modal } from "./modal";
import { paymentLabels } from "./work-report-form";

export function WorkReports({ technicianId }: { technicianId: string }) {
  const { data, error, reload } = useResource<WorkReportList>(
    `/technicians/${technicianId}/work-reports`,
  );
  const [selected, setSelected] = useState<WorkReport | null>(null);
  const detail = selected?.technician_id === technicianId ? selected : null;
  return (
    <section className="panel work-reports">
      <div className="panel-heading">
        <h2>Work reports</h2>
        <button className="button" onClick={reload}>
          Refresh reports
        </button>
      </div>
      <p className="muted">
        Latest 20 submissions · read only · not accounting
      </p>
      <ErrorNotice message={error} retry={reload} />
      {!data && !error && <Loading />}
      {data && (
        <>
          <p>{data.reports.length} reports shown</p>
          {data.reports.length === 0 && <p>No reports submitted.</p>}
          {data.reports.map((report) => (
            <button
              className="report-job"
              key={report.id}
              onClick={() => setSelected(report)}
            >
              <span>
                {report.operational_date} · {report.start_time}
              </span>
              <strong>{report.title}</strong>
              <span>
                {paymentLabels[report.payment_method]} · ${report.amount_closed}
              </span>
            </button>
          ))}
        </>
      )}
      {detail && (
        <Modal
          title="Work report · read only"
          onClose={() => setSelected(null)}
        >
          <dl className="report-detail">
            <dt>Technician at submission</dt>
            <dd>{detail.technician_name}</dd>
            <dt>Operational date / schedule</dt>
            <dd>
              {detail.operational_date} · {detail.start_time}–{detail.end_time}
            </dd>
            <dt>Job</dt>
            <dd>{detail.title}</dd>
            <dt>Location</dt>
            <dd>{detail.location || "Not provided"}</dd>
            <dt>Payment / outcome</dt>
            <dd>{paymentLabels[detail.payment_method]}</dd>
            <dt>Amount</dt>
            <dd>${detail.amount_closed}</dd>
            <dt>Closed by</dt>
            <dd>{detail.closed_by === "MYSELF" ? "Myself" : "Call center"}</dd>
            <dt>Reviews</dt>
            <dd>
              Google {detail.reviews.GOOGLE} · Groupon {detail.reviews.GROUPON}{" "}
              · Facebook {detail.reviews.FACEBOOK}
            </dd>
            <dt>Maintenance plan provided</dt>
            <dd>{detail.yearly_maintenance_plan_provided ? "Yes" : "No"}</dd>
            <dt>Comments</dt>
            <dd className="report-notes">{detail.comments || "None"}</dd>
            <dt>Revision</dt>
            <dd>{detail.revision_number}</dd>
            <dt>Submitted</dt>
            <dd>{new Date(detail.submitted_at).toLocaleString()}</dd>
          </dl>
        </Modal>
      )}
    </section>
  );
}
