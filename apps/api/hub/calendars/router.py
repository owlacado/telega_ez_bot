from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.calendars.models import Calendar, CalendarAssignment
from hub.calendars.schemas import CalendarCreate, CalendarRead
from hub.calendars.service import calendar_rows
from hub.core.database import session
from hub.technicians.schemas import DeleteConfirmation

router = APIRouter(prefix="/api/calendars", tags=["calendars"])


class CalendarDelete(DeleteConfirmation):
    detach_assigned: bool = False


@router.get("", response_model=list[CalendarRead])
async def list_calendars(db: AsyncSession = Depends(session)) -> list[dict]:
    return await calendar_rows(db)


@router.post("", response_model=CalendarRead, status_code=201)
async def create_calendar(
    payload: CalendarCreate, db: AsyncSession = Depends(session)
) -> CalendarRead:
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
    calendar_id: UUID, payload: CalendarCreate, db: AsyncSession = Depends(session)
) -> dict:
    calendar = await db.get(Calendar, calendar_id, with_for_update=True)
    if not calendar:
        raise HTTPException(404, "Calendar not found.")
    calendar.name = payload.name
    await db.flush()
    response = next(row for row in await calendar_rows(db) if row["id"] == calendar_id)
    await db.commit()
    return response


@router.delete("/{calendar_id}", status_code=204)
async def delete_calendar(
    calendar_id: UUID, payload: CalendarDelete, db: AsyncSession = Depends(session)
) -> Response:
    calendar = await db.get(Calendar, calendar_id, with_for_update=True)
    if not calendar:
        raise HTTPException(404, "Calendar not found.")
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
