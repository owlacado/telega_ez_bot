from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.calendars.models import Calendar, CalendarAssignment
from hub.google_calendar.service import mutation_lock
from hub.technicians.models import Technician
from hub.technicians.service import require_technician


async def assign_calendar(
    db: AsyncSession,
    technician_id: UUID,
    calendar_id: UUID,
    actor_id: UUID | None = None,
    *,
    allow_demo: bool = True,
) -> CalendarAssignment:
    await mutation_lock(db)
    # Serialize changes for this identity; partial unique indexes also protect concurrent writes.
    await require_technician(db, technician_id, lock=True)
    calendar = await db.scalar(select(Calendar).where(Calendar.id == calendar_id).with_for_update())
    if calendar is None:
        raise HTTPException(404, "Calendar not found.")
    if calendar.source == "LOCAL_DEMO" and not allow_demo:
        raise HTTPException(403, "Demo calendars cannot be assigned in production.")
    if calendar.excluded_at is not None or calendar.availability != "AVAILABLE":
        raise HTTPException(
            409, "This calendar is excluded or unavailable. Choose an available calendar."
        )
    existing = await db.scalar(
        select(CalendarAssignment).where(
            CalendarAssignment.calendar_id == calendar_id, CalendarAssignment.is_active.is_(True)
        )
    )
    if existing:
        if existing.technician_id == technician_id:
            return existing
        raise HTTPException(409, "This calendar is already assigned to another technician.")
    previous = await db.scalar(
        select(CalendarAssignment.id).where(
            CalendarAssignment.technician_id == technician_id,
            CalendarAssignment.is_active.is_(True),
        )
    )
    await db.execute(
        update(CalendarAssignment)
        .where(
            CalendarAssignment.technician_id == technician_id,
            CalendarAssignment.is_active.is_(True),
        )
        .values(is_active=False)
    )
    assignment = CalendarAssignment(
        technician_id=technician_id, calendar_id=calendar_id, calendar_name=calendar.name
    )
    db.add(assignment)
    await db.flush()
    audit(
        db,
        "calendar.reassigned" if previous else "calendar.assigned",
        calendar.id,
        actor_id=actor_id,
    )
    return assignment


async def unassign_calendar(
    db: AsyncSession, technician_id: UUID, actor_id: UUID | None = None
) -> None:
    await mutation_lock(db)
    await require_technician(db, technician_id, lock=True)
    await db.execute(
        update(CalendarAssignment)
        .where(
            CalendarAssignment.technician_id == technician_id,
            CalendarAssignment.is_active.is_(True),
        )
        .values(is_active=False)
    )
    audit(db, "calendar.unassigned", technician_id, actor_id=actor_id)


async def calendar_rows(db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(Calendar, Technician)
            .outerjoin(
                CalendarAssignment,
                (CalendarAssignment.calendar_id == Calendar.id)
                & CalendarAssignment.is_active.is_(True),
            )
            .outerjoin(Technician, Technician.id == CalendarAssignment.technician_id)
            .order_by(Calendar.name)
        )
    ).all()
    return [
        {
            "id": calendar.id,
            "name": calendar.name,
            "source": calendar.source,
            "availability": calendar.availability,
            "excluded_at": calendar.excluded_at,
            "timezone": calendar.timezone,
            "primary": calendar.primary,
            "access_role": calendar.access_role,
            "last_seen_at": calendar.last_seen_at,
            "created_at": calendar.created_at,
            "updated_at": calendar.updated_at,
            "assigned_technician": {
                "id": technician.id,
                "name": f"{technician.first_name} {technician.last_name}",
            }
            if technician
            else None,
        }
        for calendar, technician in rows
    ]
