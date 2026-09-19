from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.calendars.models import CalendarAssignment
from hub.calendars.schemas import AssignmentInput, AssignmentRead
from hub.calendars.service import assign_calendar, unassign_calendar
from hub.core.database import session
from hub.technicians.models import Technician
from hub.technicians.schemas import (
    TechnicianCreate,
    TechnicianDelete,
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
    q: str = Query(default="", max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$"),
    db: AsyncSession = Depends(session),
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
    payload: TechnicianCreate, request: Request, db: AsyncSession = Depends(session)
) -> TechnicianDetail:
    technician = Technician(
        first_name=payload.first_name,
        last_name=payload.last_name,
        photo_url=str(payload.photo_url) if payload.photo_url else None,
    )
    db.add(technician)
    await db.flush()
    if payload.calendar_id:
        await assign_calendar(
            db,
            technician.id,
            payload.calendar_id,
            request.state.manager_id,
            allow_demo=request.app.state.settings.app_env in {"development", "test"},
        )
    response = detail(await require_technician(db, technician.id))
    await db.commit()
    return response


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
        zone = values.get("accounting_timezone")
        if zone and not await db.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name=:zone)"),
            {"zone": zone},
        ):
            raise HTTPException(422, "Accounting timezone is unavailable on this server.")
        for key, value in values.items():
            setattr(technician, key, value)
        if values.get("status") == "INACTIVE":
            await invalidate(db, technician_id)
        await db.flush()
        response = detail(await require_technician(db, technician_id))
        await db.commit()
        return response


@router.delete("/{technician_id}", status_code=204)
async def delete_technician(
    technician_id: UUID,
    payload: TechnicianDelete,
    request: Request,
    db: AsyncSession = Depends(session),
) -> Response:
    async with advisory_guard(request.app.state.engine, "technician", technician_id):
        technician = await require_technician(db, technician_id, lock=True)
        if technician.updated_at != payload.expected_updated_at:
            raise HTTPException(409, "Profile changed. Reload the page and confirm deletion again.")
        from hub.expenses.models import TechnicianExpense
        from hub.work_reports.models import WorkReport

        if await db.scalar(
            select(WorkReport.id).where(WorkReport.technician_id == technician_id).limit(1)
        ) or await db.scalar(
            select(TechnicianExpense.id)
            .where(TechnicianExpense.technician_id == technician_id)
            .limit(1)
        ):
            raise HTTPException(
                409,
                "Technician has business records and cannot be permanently deleted. "
                "Deactivate the technician instead.",
            )
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
    technician_id: UUID,
    payload: AssignmentInput,
    request: Request,
    db: AsyncSession = Depends(session),
) -> AssignmentRead:
    assignment = await assign_calendar(
        db,
        technician_id,
        payload.calendar_id,
        request.state.manager_id,
        allow_demo=request.app.state.settings.app_env in {"development", "test"},
    )
    response = AssignmentRead.model_validate(assignment)
    await db.commit()
    return response


@router.delete("/{technician_id}/calendar", status_code=204)
async def remove_calendar_assignment(
    technician_id: UUID, request: Request, db: AsyncSession = Depends(session)
) -> Response:
    await unassign_calendar(db, technician_id, request.state.manager_id)
    await db.commit()
    return Response(status_code=204)
