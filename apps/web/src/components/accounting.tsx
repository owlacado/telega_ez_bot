"use client";
import { useState } from "react";
import type {
  DailyAccounting,
  WeeklyAccounting,
  CurrentAccounting,
  AccountingTotals,
} from "@hub/contracts";
import { useResource } from "@/lib/use-resource";
import { download, errorMessage } from "@/lib/api";
import { ErrorNotice, Loading } from "./ui";
import { AccountingMirror } from "./accounting-mirror";

const labels: Record<string, string> = {
  CASH: "Cash",
  ZELLE: "Zelle",
  CHECK: "Check",
  CREDIT_CARD: "Credit Card / Cash App",
  VENMO: "Venmo",
  SUPER: "SUPER",
  ESTIMATE: "Estimate",
  CANCEL: "Cancel",
  MYSELF: "Myself",
  CALL_CENTER: "Call center",
  GOOGLE: "Google",
  GROUPON: "Groupon",
  FACEBOOK: "Facebook",
};
export function Totals({
  value,
  compact = false,
}: {
  value: AccountingTotals;
  compact?: boolean;
}) {
  return (
    <div className="accounting-totals">
      <dl className="accounting-metrics">
        <div>
          <dt>Reported gross</dt>
          <dd>${value.gross_total}</dd>
        </div>
        <div>
          <dt>Expenses</dt>
          <dd>${value.expense_total}</dd>
        </div>
        <div>
          <dt>Reports</dt>
          <dd>{value.report_count}</dd>
        </div>
        <div>
          <dt>Maintenance plans</dt>
          <dd>{value.maintenance_count}</dd>
        </div>
      </dl>
      <p className="accounting-reviews">
        {Object.entries(value.reviews).map(([code, count]) => (
          <span key={code}>
            {labels[code]} reviews: <strong>{count}</strong>
          </span>
        ))}
      </p>
      {!compact && (
        <>
          <dl className="accounting-buckets">
            {Object.entries(value.payments).map(([code, amount]) => (
              <div key={code}>
                <dt>{labels[code]}</dt>
                <dd>${amount}</dd>
              </div>
            ))}
          </dl>
          <p>
            Closed by Myself: {value.closed_by.MYSELF} · Call center:{" "}
            {value.closed_by.CALL_CENTER}
          </p>
          <p>{value.expense_count} expense entries</p>
        </>
      )}
    </div>
  );
}
function Day({ day }: { day: DailyAccounting }) {
  return (
    <div className="accounting-day">
      <Totals value={day.totals} />
      <h4>Work reports</h4>
      {day.reports.length === 0 && <p>No work reports for this date.</p>}
      {day.reports.map((r) => (
        <article className="accounting-fact" key={r.id}>
          <div>
            <strong>
              {r.sequence}. {r.title}
            </strong>
            <span>
              {r.start_time}–{r.end_time}
            </span>
          </div>
          <p>{r.location}</p>
          <p>
            ${r.amount} · {labels[r.payment_method]} · {labels[r.closed_by]}
          </p>
          <p>
            Google {r.google_reviews} · Groupon {r.groupon_reviews} · Facebook{" "}
            {r.facebook_reviews} · Maintenance {r.maintenance ? "Yes" : "No"}
          </p>
          {r.comments && <p className="report-notes">{r.comments}</p>}
          <small>Revision {r.revision_number}</small>
        </article>
      ))}
      <h4>Expense entries</h4>
      {day.expenses.length === 0 && <p>No expenses for this date.</p>}
      {day.expenses.map((e) => (
        <article className="accounting-fact" key={e.id}>
          <strong>
            {e.expense_type} · ${e.amount}
          </strong>
          {e.note && <p className="report-notes">{e.note}</p>}
          <small>
            {e.accounting_timezone} · Revision {e.revision_number}
          </small>
        </article>
      ))}
    </div>
  );
}
function Current({ id }: { id: string }) {
  const { data, error, reload } = useResource<CurrentAccounting>(
    `/technicians/${id}/accounting/current`,
  );
  return (
    <>
      <button className="button" onClick={reload}>
        Refresh accounting
      </button>
      <ErrorNotice message={error} retry={reload} />
      {!data && !error && <Loading />}
      {data && !error && (
        <>
          <p className="muted">
            Accounting timezone: {data.accounting_timezone || "Not configured"}
          </p>
          {data.setup_required ? (
            <p>
              Today’s total unavailable: configure accounting timezone. Select
              an explicit date to view history.
            </p>
          ) : (
            <>
              <section aria-label="Today accounting">
                <h3>Today · {data.today}</h3>
                <Totals value={data.daily!.totals} compact />
              </section>
              <section aria-label="This week accounting">
                <h3>
                  This Week · {data.weekly!.week_start} –{" "}
                  {data.weekly!.week_end}
                </h3>
                <Totals value={data.weekly!.totals} compact />
              </section>
            </>
          )}
        </>
      )}
    </>
  );
}
function Detail({ id, mode }: { id: string; mode: "daily" | "weekly" }) {
  const [selector, setSelector] = useState("");
  const [downloading, setDownloading] = useState<"individual" | "all" | null>(
    null,
  );
  const [downloadError, setDownloadError] = useState("");
  const { data, error, reload } = useResource<
    DailyAccounting | WeeklyAccounting
  >(
    `/technicians/${id}/accounting/${mode}${selector ? `?${mode === "daily" ? "date" : "week_start"}=${selector}` : ""}`,
  );
  const day = data && "business_date" in data ? data : null;
  const week = data && "week_start" in data ? data : null;
  const previous = day?.previous_date ?? week?.previous_week;
  const next = day?.next_date ?? week?.next_week;
  async function downloadWorkbook(kind: "individual" | "all") {
    if (!week || downloading) return;
    setDownloadError("");
    setDownloading(kind);
    try {
      const path =
        kind === "individual"
          ? `/technicians/${id}/accounting/weekly.xlsx?week_start=${week.week_start}`
          : `/accounting/weekly/all.xlsx?week_start=${week.week_start}`;
      await download(path);
    } catch (downloadFailure) {
      setDownloadError(errorMessage(downloadFailure));
    } finally {
      setDownloading(null);
    }
  }
  return (
    <>
      <div className="accounting-navigation">
        <button
          className="button"
          disabled={!previous || !!error}
          onClick={() => setSelector(previous!)}
        >
          Previous {mode === "daily" ? "day" : "week"}
        </button>
        <button className="button" onClick={() => setSelector("")}>
          {mode === "daily" ? "Today" : "Current week"}
        </button>
        <button
          className="button"
          disabled={!next || !!error}
          onClick={() => setSelector(next!)}
        >
          Next {mode === "daily" ? "day" : "week"}
        </button>
        <button className="button" onClick={reload}>
          Refresh accounting
        </button>
        <label>
          {mode === "daily" ? "Business date" : "Week starting Monday"}
          <input
            type="date"
            value={selector || day?.business_date || week?.week_start || ""}
            onChange={(e) => setSelector(e.target.value)}
          />
        </label>
      </div>
      <ErrorNotice message={error} retry={reload} />
      {downloadError && <ErrorNotice message={downloadError} />}
      {!data && !error && <Loading />}
      {data && !error && (
        <>
          <p className="muted">
            {data.technician_name} · Accounting timezone:{" "}
            {data.accounting_timezone || "Not configured"}
          </p>
          {data.setup_required && (
            <p>
              Setup required for Today / Current week. Stored historical dates
              remain available.
            </p>
          )}
          {day && (
            <>
              <h3>Daily · {day.business_date}</h3>
              <Day day={day} />
            </>
          )}
          {week && (
            <>
              <h3>
                Weekly · {week.week_start} – {week.week_end}
              </h3>
              <div className="accounting-navigation">
                <button
                  className="button primary"
                  disabled={downloading !== null}
                  onClick={() => downloadWorkbook("individual")}
                >
                  {downloading === "individual"
                    ? "Preparing XLSX…"
                    : "Download XLSX"}
                </button>
                <button
                  className="button"
                  disabled={downloading !== null}
                  onClick={() => downloadWorkbook("all")}
                >
                  {downloading === "all"
                    ? "Preparing all technicians…"
                    : "Download All Tech XLSX"}
                </button>
              </div>
              <AccountingMirror technicianId={id} weekStart={week.week_start} />
              <AccountingMirror
                technicianId={id}
                weekStart={week.week_start}
                allTechnicians
              />
              <Totals value={week.totals} />
              {week.days.map((d) => (
                <details className="accounting-date" key={d.business_date}>
                  <summary>
                    {
                      [
                        "Monday",
                        "Tuesday",
                        "Wednesday",
                        "Thursday",
                        "Friday",
                        "Saturday",
                        "Sunday",
                      ][week.days.indexOf(d)]
                    }{" "}
                    · {d.business_date} · ${d.totals.gross_total} gross · $
                    {d.totals.expense_total} expenses
                  </summary>
                  <Day day={d} />
                </details>
              ))}
            </>
          )}
        </>
      )}
    </>
  );
}
export function Accounting({ technicianId }: { technicianId: string }) {
  const [mode, setMode] = useState<"current" | "daily" | "weekly">("current");
  return (
    <section className="panel accounting">
      <div className="panel-heading">
        <h2>Accounting</h2>
        <span className="muted">Current saved revisions</span>
      </div>
      <div className="accounting-body">
        <nav aria-label="Accounting views" className="accounting-navigation">
          {(["current", "daily", "weekly"] as const).map((m) => (
            <button
              className={`button ${mode === m ? "primary" : ""}`}
              key={m}
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
            >
              {m === "current"
                ? "Overview"
                : m === "daily"
                  ? "Daily report"
                  : "Weekly report"}
            </button>
          ))}
        </nav>
        {mode === "current" ? (
          <Current key={technicianId} id={technicianId} />
        ) : (
          <Detail
            key={`${technicianId}:${mode}`}
            id={technicianId}
            mode={mode}
          />
        )}
      </div>
    </section>
  );
}
