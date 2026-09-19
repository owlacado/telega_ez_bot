"use client";
import { useState } from "react";
import type { ExpenseRead, ExpenseList } from "@hub/contracts";
import { useResource } from "@/lib/use-resource";
import { ErrorNotice, Loading } from "./ui";
import { Modal } from "./modal";
export function Expenses({ technicianId }: { technicianId: string }) {
  const { data, error, reload } = useResource<ExpenseList>(
    `/technicians/${technicianId}/expenses`,
  );
  const [selected, setSelected] = useState<ExpenseRead | null>(null);
  const detail = selected?.technician_id === technicianId ? selected : null;
  return (
    <section className="panel work-reports">
      <div className="panel-heading">
        <h2>Expenses</h2>
        <button className="button" onClick={reload}>
          Refresh expenses
        </button>
      </div>
      <p className="muted">Read only · expense facts, not full accounting</p>
      <ErrorNotice message={error} retry={reload} />
      {!data && !error && <Loading />}
      {data && (
        <>
          {data.today ? (
            <p>
              Today ({data.today}, {data.accounting_timezone}): $
              {data.today_total} · {data.today_count} expenses
            </p>
          ) : (
            <p>Today’s total unavailable: configure accounting timezone.</p>
          )}
          <p>
            Latest {data.limit} submissions · {data.expenses.length} expenses
            shown
          </p>
          {data.expenses.length === 0 && <p>No expenses submitted.</p>}
          {data.expenses.map((e) => (
            <button
              className="report-job"
              key={e.id}
              onClick={() => setSelected(e)}
            >
              <span>{e.expense_date}</span>
              <strong>
                {e.expense_type} · ${e.amount}
              </strong>
            </button>
          ))}
        </>
      )}
      {detail && (
        <Modal title="Expense · read only" onClose={() => setSelected(null)}>
          <dl className="report-detail">
            <dt>Technician at submission</dt>
            <dd>{detail.technician_name}</dd>
            <dt>Business date</dt>
            <dd>
              {detail.expense_date} · {detail.accounting_timezone}
            </dd>
            <dt>Expense type</dt>
            <dd>{detail.expense_type}</dd>
            <dt>Amount</dt>
            <dd>${detail.amount}</dd>
            <dt>Note</dt>
            <dd className="report-notes">{detail.note || "None"}</dd>
            <dt>Receipt</dt>
            <dd>No receipt stored in Technician Hub</dd>
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
