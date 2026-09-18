from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.core.database import session
from hub.technicians.service import require_technician
from hub.work_reports import service
from hub.work_reports.models import TechnicianFormSession, WorkReport, WorkReportRevision
from hub.work_reports.schemas import (
    FormRead,
    ReportInput,
    ReportList,
    ReportRead,
    SelectJob,
    SubmissionRead,
)

router = APIRouter(tags=["work-reports"])
FORM_PATHS = {
    "/api/technician-forms/work-report",
    "/api/technician-forms/work-report/select",
    "/api/technician-forms/work-report/submit",
}


def capability(request: Request):
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer "):
        service.unavailable()
    return value[7:]


@router.post("/api/technician-forms/work-report", response_model=FormRead)
async def open_form(request: Request):
    return await service.open_form(request, capability(request))


@router.post("/api/technician-forms/work-report/select", response_model=FormRead)
async def select_job(payload: SelectJob, request: Request):
    return await service.select_job(
        request.app.state.session_factory, capability(request), payload.choice_id
    )


@router.post("/api/technician-forms/work-report/submit", response_model=SubmissionRead)
async def submit(payload: ReportInput, request: Request):
    return await service.submit(request.app.state.session_factory, capability(request), payload)


@router.get("/api/technicians/{technician_id}/work-reports", response_model=ReportList)
async def reports(
    technician_id: UUID, limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(session)
):
    await require_technician(db, technician_id)
    rows = await db.execute(
        service.current_reports()
        .where(WorkReport.technician_id == technician_id)
        .order_by(WorkReportRevision.submitted_at.desc(), WorkReport.id)
        .limit(limit)
    )
    return ReportList(
        reports=[service.report_view(report, revision) for report, revision in rows], limit=limit
    )


@router.get("/api/work-reports/{report_id}", response_model=ReportRead)
async def report(report_id: UUID, db: AsyncSession = Depends(session)):
    row = (await db.execute(service.current_reports().where(WorkReport.id == report_id))).first()
    if not row:
        raise HTTPException(404, "Report not found.")
    return service.report_view(*row)


@router.post(
    "/api/technicians/{technician_id}/work-report-sessions/{session_id}/revoke", status_code=204
)
async def revoke(
    technician_id: UUID, session_id: UUID, request: Request, db: AsyncSession = Depends(session)
):
    await require_technician(db, technician_id, lock=True)
    value = await db.get(TechnicianFormSession, session_id, with_for_update=True)
    if not value or value.technician_id != technician_id:
        raise HTTPException(404, "Form not found.")
    if value.status == "OPEN":
        value.status, value.choices, value.selected = "REVOKED", None, None
        audit(db, "work_report.session_revoked", value.id, actor_id=request.state.manager_id)
    await db.commit()
    return Response(status_code=204)
