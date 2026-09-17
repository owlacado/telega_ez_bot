import Link from "next/link";
import {
  ArrowUpRight,
  CalendarDays,
  MessageCircle,
  Radio,
  UsersRound,
} from "lucide-react";
import type { Technician } from "@hub/contracts";
import { statusLabel } from "@hub/shared";
import { Avatar, Status } from "./ui";
export function TechnicianCard({ technician: t }: { technician: Technician }) {
  const indicators = [
    {
      label: "Telegram",
      status: t.integrations.telegram_private,
      Icon: MessageCircle,
    },
    { label: "Group", status: t.integrations.telegram_group, Icon: UsersRound },
    { label: "GPS", status: t.integrations.gps_status, Icon: Radio },
  ];
  return (
    <Link
      className="technician-card"
      href={`/technicians/${t.id}`}
      aria-label={`Open ${t.first_name} ${t.last_name}`}
    >
      <div className="card-topline">
        <span className="eyebrow">TECHNICIAN</span>
        <Status value={t.status} />
      </div>
      <div className="card-identity">
        <Avatar
          firstName={t.first_name}
          lastName={t.last_name}
          url={t.photo_url}
          large
        />
        <div>
          <h2>
            <span>{t.first_name}</span>
            <span>{t.last_name}</span>
          </h2>
          <span className="record-id">
            ID · {t.id.slice(0, 8).toUpperCase()}
          </span>
        </div>
        <ArrowUpRight className="card-arrow" size={19} />
      </div>
      <div className="card-calendar">
        <CalendarDays size={17} />
        <div>
          <span className="micro-label">ASSIGNED CALENDAR</span>
          <span className={!t.calendar ? "muted" : ""}>
            {t.calendar?.name ?? "Not assigned"}
          </span>
        </div>
      </div>
      <div className="card-integrations">
        {indicators.map(({ label, status, Icon }) => (
          <span
            key={label}
            className={`integration-indicator ${status === "CONNECTED" ? "connected" : ""}`}
            title={`${label}: ${statusLabel(status)}`}
            aria-label={`${label}: ${statusLabel(status)}`}
          >
            <Icon size={14} />
            <span>{label}</span>
            <i />
          </span>
        ))}
      </div>
    </Link>
  );
}
