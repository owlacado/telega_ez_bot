from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.auth.security import now
from hub.calendars.models import Calendar, CalendarAssignment
from hub.calendars.schemas import CalendarAssign, CalendarCreate, CalendarExclude, CalendarRead
from hub.calendars.service import assign_calendar, calendar_rows, unassign_calendar
from hub.core.database import session
from hub.google_calendar.service import mutation_lock
from hub.technicians.schemas import DeleteConfirmation

router = APIRouter(prefix="/api/calendars", tags=["calendars"])


class CalendarDelete(DeleteConfirmation):
    detach_assigned: bool = False


@router.get("", response_model=list[CalendarRead])
async def list_calendars(request: Request, db: AsyncSession = Depends(session)) -> list[dict]:
    rows = await calendar_rows(db)
    return (
        rows
        if request.app.state.settings.app_env in {"development", "test"}
        else [row for row in rows if row["source"] == "GOOGLE"]
    )


def demo_only(request, calendar=None):
    if request.app.state.settings.app_env not in {"development", "test"} or (
        calendar and calendar.source != "LOCAL_DEMO"
    ):
        raise HTTPException(
            403, "Local calendar editing is available only for development/demo records."
        )


@router.post("", response_model=CalendarRead, status_code=201)
async def create_calendar(
    payload: CalendarCreate, request: Request, db: AsyncSession = Depends(session)
) -> CalendarRead:
    demo_only(request)
    calendar = Calendar(name=payload.name)
    db.add(calendar)
    await db.flush()
    response = CalendarRead(
        id=calendar.id,
        name=calendar.name,
        created_at=calendar.created_at,
        updated_at=calendar.updated_at,
    )
    await db.commit()
    return response


@router.patch("/{calendar_id}", response_model=CalendarRead)
async def rename_calendar(
    calendar_id: UUID,
    payload: CalendarCreate,
    request: Request,
    db: AsyncSession = Depends(session),
) -> dict:
    await mutation_lock(db)
    calendar = await db.get(Calendar, calendar_id, with_for_update=True)
    if not calendar:
        raise HTTPException(404, "Calendar not found.")
    demo_only(request, calendar)
    calendar.name = payload.name
    await db.flush()
    response = next(row for row in await calendar_rows(db) if row["id"] == calendar_id)
    await db.commit()
    return response


@router.delete("/{calendar_id}", status_code=204)
async def delete_calendar(
    calendar_id: UUID,
    payload: CalendarDelete,
    request: Request,
    db: AsyncSession = Depends(session),
) -> Response:
    await mutation_lock(db)
    calendar = await db.get(Calendar, calendar_id, with_for_update=True)
    if not calendar:
        raise HTTPException(404, "Calendar not found.")
    demo_only(request, calendar)
    assigned = await db.scalar(
        select(CalendarAssignment.id).where(
            CalendarAssignment.calendar_id == calendar_id, CalendarAssignment.is_active.is_(True)
        )
    )
    if assigned and not payload.detach_assigned:
        raise HTTPException(
            409, "This calendar is assigned. Confirm that its technician will become unassigned."
        )
    await db.execute(
        update(CalendarAssignment)
        .where(CalendarAssignment.calendar_id == calendar_id)
        .values(is_active=False)
    )
    await db.delete(calendar)
    await db.commit()
    return Response(status_code=204)


async def selected_calendar(db, identifier, expected_technician):
    await mutation_lock(db)
    calendar = await db.get(Calendar, identifier, with_for_update=True)
    if calendar is None:
        raise HTTPException(404, "Calendar not found.")
    assignment = await db.scalar(
        select(CalendarAssignment).where(
            CalendarAssignment.calendar_id == identifier, CalendarAssignment.is_active.is_(True)
        )
    )
    if (assignment.technician_id if assignment else None) != expected_technician:
        raise HTTPException(409, "Assignment changed. Refresh and confirm again.")
    return calendar, assignment


@router.post("/{calendar_id}/exclude", status_code=204)
async def exclude_calendar(
    calendar_id: UUID,
    payload: CalendarExclude,
    request: Request,
    db: AsyncSession = Depends(session),
):
    calendar, assignment = await selected_calendar(
        db, calendar_id, payload.expected_assigned_technician_id
    )
    if calendar.source != "GOOGLE":
        raise HTTPException(409, "Only discovered Google calendars use exclusions.")
    if assignment:
        await unassign_calendar(db, assignment.technician_id, request.state.manager_id)
        audit(db, "calendar.assigned_removed", calendar.id, actor_id=request.state.manager_id)
    calendar.excluded_at, calendar.excluded_by = now(), request.state.manager_id
    audit(db, "calendar.excluded", calendar.id, actor_id=request.state.manager_id)
    await db.commit()
    return Response(status_code=204)


@router.post("/{calendar_id}/restore", status_code=204)
async def restore_calendar(
    calendar_id: UUID, request: Request, db: AsyncSession = Depends(session)
):
    await mutation_lock(db)
    calendar = await db.get(Calendar, calendar_id, with_for_update=True)
    if calendar is None:
        raise HTTPException(404, "Calendar not found.")
    if calendar.source != "GOOGLE":
        raise HTTPException(409, "Only discovered Google calendars use exclusions.")
    calendar.excluded_at, calendar.excluded_by = None, None
    audit(db, "calendar.restored", calendar.id, actor_id=request.state.manager_id)
    await db.commit()
    return Response(status_code=204)


@router.put("/{calendar_id}/assignment", status_code=204)
async def change_assignment(
    calendar_id: UUID,
    payload: CalendarAssign,
    request: Request,
    db: AsyncSession = Depends(session),
):
    calendar, assignment = await selected_calendar(
        db, calendar_id, payload.expected_assigned_technician_id
    )
    if calendar.source == "LOCAL_DEMO":
        demo_only(request, calendar)
    if assignment:
        await unassign_calendar(db, assignment.technician_id, request.state.manager_id)
    if payload.technician_id:
        await assign_calendar(db, payload.technician_id, calendar_id, request.state.manager_id)
    await db.commit()
    return Response(status_code=204)
