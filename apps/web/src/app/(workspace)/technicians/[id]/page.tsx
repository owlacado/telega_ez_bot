"use client";
import { use } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { TechnicianDetail } from "@hub/contracts";
import { useResource } from "@/lib/use-resource";
import { Avatar, ErrorNotice, Loading, Status } from "@/components/ui";
import { TodayJobs, PreviewSchedule } from "@/components/calendar-jobs";
import { useSchedule } from "@/lib/use-schedule";
import { ProfilePanel } from "@/components/profile-panel";
import { GpsPanel } from "@/components/detail-placeholders";
import { Accounting } from "@/components/accounting";
import { PilotReadiness } from "@/components/pilot-readiness";
export default function TechnicianDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const {
    data: technician,
    error,
    reload,
    setData,
  } = useResource<TechnicianDetail>(`/technicians/${id}`);
  const jobs = useSchedule(
    technician ? `/technicians/${id}/calendar/today` : null,
    technician?.calendar?.id ?? "",
  );
  return (
    <>
      <Link href="/technicians" className="back-link">
        <ArrowLeft size={16} />
        Back to Technicians
      </Link>
      <ErrorNotice message={error} retry={reload} />
      {!technician ? (
        !error && <Loading />
      ) : (
        <>
          <div className="detail-heading">
            <Avatar
              firstName={technician.first_name}
              lastName={technician.last_name}
              large
            />
            <div className="detail-title">
              <div className="eyebrow">TECHNICIAN PROFILE</div>
              <h1>
                {technician.first_name} {technician.last_name}
              </h1>
              <div className="detail-subtitle">
                <Status value={technician.status} />
                <span className="record-id">
                  ID · {technician.id.slice(0, 8).toUpperCase()}
                </span>
              </div>
            </div>
            <PreviewSchedule
              key={`${id}:${technician.calendar?.id}`}
              id={id}
              today={jobs.data}
            />
          </div>
          <div className="detail-grid">
            <PilotReadiness readiness={technician.pilot_readiness} />
            <ProfilePanel
              key={id}
              technician={technician}
              onUpdate={setData}
              onMissing={() => {
                setData(null);
                reload();
              }}
            />
            <Accounting
              key={`accounting:${id}:${technician.accounting_timezone}`}
              technicianId={id}
            />
            <TodayJobs resource={jobs} />
            <GpsPanel />
          </div>
        </>
      )}
    </>
  );
}
