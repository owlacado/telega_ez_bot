from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.calendars.models import CalendarAssignment
from hub.calendars.schemas import AssignmentInput, AssignmentRead
from hub.calendars.service import assign_calendar, unassign_calendar
from hub.core.database import session
from hub.technicians.models import Technician
from hub.technicians.schemas import (
    DeleteConfirmation,
    TechnicianCreate,
    TechnicianDetail,
    TechnicianSummary,
    TechnicianUpdate,
)
from hub.technicians.service import detail, require_technician, summary
from hub.telegram.common import invalidate
from hub.telegram.locks import advisory_guard

router = APIRouter(prefix="/api/technicians", tags=["technicians"])


@router.get("", response_model=list[TechnicianSummary])
async def list_technicians(
    q: str = Query(default="", max_length=200), db: AsyncSession = Depends(session)
) -> list[TechnicianSummary]:
    query = select(Technician).order_by(Technician.last_name, Technician.first_name, Technician.id)
    for term in q.strip().split():
        query = query.where(
            or_(
                Technician.first_name.icontains(term, autoescape=True),
                Technician.last_name.icontains(term, autoescape=True),
            )
        )
    return [summary(item) for item in (await db.scalars(query)).all()]


@router.post("", response_model=TechnicianDetail, status_code=201)
async def create_technician(
    payload: TechnicianCreate, db: AsyncSession = Depends(session)
) -> TechnicianDetail:
    technician = Technician(
        first_name=payload.first_name,
        last_name=payload.last_name,
        photo_url=str(payload.photo_url) if payload.photo_url else None,
    )
    db.add(technician)
    await db.flush()
    if payload.calendar_id:
        await assign_calendar(db, technician.id, payload.calendar_id)
    await db.commit()
    return detail(await require_technician(db, technician.id))


@router.get("/{technician_id}", response_model=TechnicianDetail)
async def get_technician(
    technician_id: UUID, db: AsyncSession = Depends(session)
) -> TechnicianDetail:
    return detail(await require_technician(db, technician_id))


@router.patch("/{technician_id}", response_model=TechnicianDetail)
async def update_technician(
    technician_id: UUID,
    payload: TechnicianUpdate,
    request: Request,
    db: AsyncSession = Depends(session),
) -> TechnicianDetail:
    async with advisory_guard(request.app.state.engine, "technician", technician_id):
        technician = await require_technician(db, technician_id, lock=True)
        values = payload.model_dump(mode="json", exclude_unset=True)
        for key, value in values.items():
            setattr(technician, key, value)
        if values.get("status") == "INACTIVE":
            await invalidate(db, technician_id)
        await db.commit()
        return detail(await require_technician(db, technician_id))


@router.delete("/{technician_id}", status_code=204)
async def delete_technician(
    technician_id: UUID,
    payload: DeleteConfirmation,
    request: Request,
    db: AsyncSession = Depends(session),
) -> Response:
    async with advisory_guard(request.app.state.engine, "technician", technician_id):
        technician = await require_technician(db, technician_id, lock=True)
        audit(db, "technician.deleted", technician_id, actor_id=request.state.manager_id)
        await db.delete(technician)
        await db.commit()
        return Response(status_code=204)


@router.get("/{technician_id}/calendar-assignments", response_model=list[AssignmentRead])
async def assignment_history(
    technician_id: UUID, db: AsyncSession = Depends(session)
) -> list[CalendarAssignment]:
    await require_technician(db, technician_id)
    return list(
        (
            await db.scalars(
                select(CalendarAssignment)
                .where(CalendarAssignment.technician_id == technician_id)
                .order_by(CalendarAssignment.created_at, CalendarAssignment.id)
            )
        ).all()
    )


@router.put("/{technician_id}/calendar", response_model=AssignmentRead)
async def set_calendar(
    technician_id: UUID, payload: AssignmentInput, db: AsyncSession = Depends(session)
) -> CalendarAssignment:
    assignment = await assign_calendar(db, technician_id, payload.calendar_id)
    await db.commit()
    await db.refresh(assignment)
    return assignment


@router.delete("/{technician_id}/calendar", status_code=204)
async def remove_calendar_assignment(
    technician_id: UUID, db: AsyncSession = Depends(session)
) -> Response:
    await unassign_calendar(db, technician_id)
    await db.commit()
    return Response(status_code=204)
