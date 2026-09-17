from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.technicians.models import Technician
from hub.technicians.schemas import (
    CalendarSummary,
    IntegrationSummary,
    TechnicianDetail,
    TechnicianSummary,
)


async def require_technician(
    db: AsyncSession, technician_id: UUID, *, lock: bool = False
) -> Technician:
    query = select(Technician).where(Technician.id == technician_id)
    if lock:
        query = query.with_for_update()
    technician = await db.scalar(query.execution_options(populate_existing=True))
    if technician is None:
        raise HTTPException(404, "Technician not found.")
    return technician


def summary(technician: Technician) -> TechnicianSummary:
    assignment = next(
        (item for item in technician.assignments if item.is_active and item.calendar is not None),
        None,
    )
    telegram, gps = technician.telegram, technician.gps
    return TechnicianSummary(
        id=technician.id,
        first_name=technician.first_name,
        last_name=technician.last_name,
        photo_url=technician.photo_url,
        status=technician.status,
        calendar=CalendarSummary(id=assignment.calendar.id, name=assignment.calendar.name)
        if assignment
        else None,
        integrations=IntegrationSummary(
            telegram_private=(
                telegram.private_status
                if telegram.private_availability == "AVAILABLE"
                else "ERROR"
                if telegram.telegram_user_id
                else "NOT_CONNECTED"
            )
            if telegram
            else "NOT_CONNECTED",
            telegram_group=(
                telegram.group_status
                if telegram.group_availability == "AVAILABLE"
                and telegram.private_availability == "AVAILABLE"
                and telegram.group_private_generation == telegram.private_generation
                else "ERROR"
                if telegram.telegram_group_chat_id
                else "NOT_CONNECTED"
            )
            if telegram
            else "NOT_CONNECTED",
            gps_provider=gps.provider if gps else "NONE",
            gps_status=gps.status if gps else "NOT_CONNECTED",
        ),
        created_at=technician.created_at,
        updated_at=technician.updated_at,
    )


def detail(technician: Technician) -> TechnicianDetail:
    return TechnicianDetail(
        **summary(technician).model_dump(),
        driver_license_id=technician.driver_license_id,
        ssn_last4=technician.ssn_last4,
    )
