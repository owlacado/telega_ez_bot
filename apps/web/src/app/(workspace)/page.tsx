"use client";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  CircleCheck,
  CircleDot,
  UsersRound,
  Wrench,
} from "lucide-react";
import type { Calendar, Technician } from "@hub/contracts";
import { useResource } from "@/lib/use-resource";
import { Avatar, EmptyState, ErrorNotice, Loading } from "@/components/ui";
import { OperationsHealthPanel } from "@/components/operations-health";
export default function Dashboard() {
  const technicians = useResource<Technician[]>("/technicians");
  const calendars = useResource<Calendar[]>("/calendars");
  const attention = technicians.data
    ?.map((t) => ({
      technician: t,
      missing: t.pilot_readiness.requirements
        .filter(
          (requirement) =>
            requirement.required && requirement.status !== "READY",
        )
        .map((requirement) => requirement.label),
    }))
    .filter((item) => !item.technician.pilot_readiness.ready);
  const loaded = technicians.data && calendars.data;
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">WORKSPACE OVERVIEW</div>
          <h1>A clear view of your team.</h1>
          <p className="muted">
            People, calendars, and the connections that keep work moving.
          </p>
        </div>
        <Link className="button secondary" href="/technicians">
          Manage technicians
          <ArrowUpRight size={16} />
        </Link>
      </div>
      <ErrorNotice
        message={technicians.error || calendars.error}
        retry={() => {
          technicians.reload();
          calendars.reload();
        }}
      />
      {!loaded ? (
        !(technicians.error || calendars.error) && <Loading />
      ) : (
        <>
          <div className="summary-grid">
            {[
              {
                title: "TECHNICIANS",
                value: (technicians.data ?? []).length,
                note: `${(technicians.data ?? []).filter((t) => t.status === "ACTIVE").length} active in your workspace`,
                Icon: UsersRound,
                href: "/technicians",
              },
              {
                title: "CALENDARS",
                value: (calendars.data ?? []).length,
                note: `${(calendars.data ?? []).filter((c) => !c.assigned_technician).length} available to assign`,
                Icon: CalendarDays,
                href: "/calendars",
              },
              {
                title: "NEEDS SETUP",
                value: attention?.length ?? 0,
                note: "Profiles with incomplete setup",
                Icon: CircleDot,
                href: "#attention",
              },
            ].map(({ title, value, note, Icon, href }) => (
              <Link href={href} className="summary-card" key={title}>
                <div>
                  <span className="eyebrow">{title}</span>
                  <Icon size={20} />
                </div>
                <strong>{value}</strong>
                <p>
                  {note}
                  <ArrowUpRight size={15} />
                </p>
              </Link>
            ))}
          </div>
          <section className="panel attention-panel" id="attention">
            <div className="panel-heading">
              <div>
                <h2>Needs Attention</h2>
                <p className="muted">
                  Finish setting up your team, one connection at a time.
                </p>
              </div>
              <span className="count-pill">{attention?.length ?? 0}</span>
            </div>
            {attention?.length ? (
              <div className="attention-list">
                {attention.map(({ technician: t, missing }) => (
                  <Link
                    href={`/technicians/${t.id}`}
                    key={t.id}
                    className="attention-row"
                  >
                    <Avatar firstName={t.first_name} lastName={t.last_name} />
                    <div className="attention-person">
                      <strong>
                        {t.first_name} {t.last_name}
                      </strong>
                      <span>{missing.join(" · ")}</span>
                    </div>
                    <ArrowRight size={18} />
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={
                  (technicians.data ?? []).length ? (
                    <CircleCheck size={26} />
                  ) : (
                    <UsersRound size={26} />
                  )
                }
                title={
                  (technicians.data ?? []).length
                    ? "Everything is set up"
                    : "Ready for your first technician"
                }
              >
                <p>
                  {(technicians.data ?? []).length
                    ? "No profiles need attention."
                    : "Add a technician and their setup checklist will appear here."}
                </p>
                <Link href="/technicians" className="text-link">
                  Go to Technicians <ArrowRight size={15} />
                </Link>
              </EmptyState>
            )}
          </section>
          <OperationsHealthPanel />
          <div className="foundation-note">
            <span className="foundation-icon">
              <Wrench size={19} />
            </span>
            <div>
              <strong>A foundation built around your people</strong>
              <p>
                Readiness comes from the API and covers the workflows available
                for a controlled technician pilot.
              </p>
            </div>
            <span className="stage-badge">STAGE 10</span>
          </div>
          <p className="page-footnote">
            Optional features remain visible without blocking core pilot
            readiness.
          </p>
        </>
      )}
    </>
  );
}
