"use client";
import { use, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Trash2 } from "lucide-react";
import type { TechnicianDetail } from "@hub/contracts";
import { useResource } from "@/lib/use-resource";
import { Avatar, ErrorNotice, Loading, Status } from "@/components/ui";
import { TodayJobs, PreviewSchedule } from "@/components/calendar-jobs";
import { useSchedule } from "@/lib/use-schedule";
import { ProfilePanel } from "@/components/profile-panel";
import { GpsPanel } from "@/components/detail-placeholders";
import { Accounting } from "@/components/accounting";
import { DeleteTechnician } from "@/components/delete-technician";
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
  const [deleting, setDeleting] = useState(false);
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
              url={technician.photo_url}
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
          <section className="danger-zone">
            <div>
              <span className="eyebrow">DANGER ZONE</span>
              <h2>Delete Technician</h2>
              <p>
                Permanently remove this profile and its integration
                relationships. This cannot be undone. Technicians with work
                reports or expenses cannot be deleted; deactivate them instead.
              </p>
            </div>
            <button
              className="button danger-outline"
              onClick={() => setDeleting(true)}
            >
              <Trash2 size={16} />
              Delete Technician
            </button>
          </section>
          {deleting && (
            <DeleteTechnician
              technician={technician}
              onClose={() => setDeleting(false)}
            />
          )}
        </>
      )}
    </>
  );
}
