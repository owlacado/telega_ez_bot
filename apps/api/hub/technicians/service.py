from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.core.config import Settings
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import EVENT_SCOPE
from hub.technicians.models import Technician
from hub.technicians.schemas import (
    CalendarSummary,
    IntegrationSummary,
    PilotRequirement,
    TechnicianDetail,
    TechnicianPilotReadiness,
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


def pilot_readiness(
    technician: Technician,
    calendar: CalendarSummary | None,
    integrations: IntegrationSummary,
    settings: Settings | None = None,
    google_connection: CalendarConnection | None = None,
) -> TechnicianPilotReadiness:
    requirements = [
        PilotRequirement(
            key="profile",
            label="Active profile",
            status="READY" if technician.status == "ACTIVE" else "BLOCKED",
            required=True,
            reason=(
                "Technician profile is active."
                if technician.status == "ACTIVE"
                else "Inactive technicians cannot receive pilot workflows."
            ),
            action=None if technician.status == "ACTIVE" else "Reactivate the technician.",
        ),
        PilotRequirement(
            key="accounting_timezone",
            label="Accounting timezone",
            status="READY" if technician.accounting_timezone else "NEEDS_ACTION",
            required=True,
            reason=(
                f"Accounting dates use {technician.accounting_timezone}."
                if technician.accounting_timezone
                else "Work Reports and Expenses require an explicit IANA timezone."
            ),
            action=None if technician.accounting_timezone else "Set the accounting timezone.",
        ),
        PilotRequirement(
            key="telegram_private",
            label="Telegram private chat",
            status="READY" if integrations.telegram_private == "CONNECTED" else "NEEDS_ACTION",
            required=True,
            reason=(
                "Private Telegram identity is connected and available."
                if integrations.telegram_private == "CONNECTED"
                else "Private Telegram is required for technician form delivery."
            ),
            action=(
                None
                if integrations.telegram_private == "CONNECTED"
                else "Complete or repair private Telegram onboarding."
            ),
        ),
        PilotRequirement(
            key="telegram_group",
            label="Telegram work group",
            status=("READY" if integrations.telegram_group == "CONNECTED" else "NEEDS_ACTION"),
            required=True,
            reason=(
                "Work group is connected and available."
                if integrations.telegram_group == "CONNECTED"
                else "A work group is required for report and expense activity."
            ),
            action=(
                "Connect or repair the work group."
                if integrations.telegram_group != "CONNECTED"
                else None
            ),
        ),
        PilotRequirement(
            key="calendar",
            label="Assigned calendar",
            status=(
                "READY" if calendar and calendar.availability == "AVAILABLE" else "NEEDS_ACTION"
            ),
            required=True,
            reason=(
                "Assigned calendar is available."
                if calendar and calendar.availability == "AVAILABLE"
                else "The assigned calendar is unavailable."
                if calendar
                else "No calendar is assigned."
            ),
            action=(
                None
                if calendar and calendar.availability == "AVAILABLE"
                else "Assign an available calendar."
            ),
        ),
    ]
    google_required = bool(calendar and calendar.source == "GOOGLE")
    google_ready = bool(
        google_required
        and google_connection
        and google_connection.is_current
        and google_connection.status == "CONNECTED"
        and EVENT_SCOPE in google_connection.granted_scopes
    )
    requirements.extend(
        [
            PilotRequirement(
                key="google_events",
                label="Google event permission",
                status=(
                    "READY" if google_ready else "NEEDS_ACTION" if google_required else "OPTIONAL"
                ),
                required=google_required,
                reason=(
                    "Google event-read permission is available."
                    if google_ready
                    else "The assigned Google calendar needs event-read permission."
                    if google_required
                    else "Google event permission is not required for a local demo calendar."
                ),
                action=(
                    "Reconnect Google and grant event-read permission."
                    if google_required and not google_ready
                    else None
                ),
            ),
            PilotRequirement(
                key="google_sheets_mirror",
                label="Google Sheets mirror",
                status="OPTIONAL",
                required=False,
                reason="Weekly Google Sheets mirroring is optional for the pilot.",
            ),
        ]
    )
    blocking = sum(
        requirement.required and requirement.status in {"BLOCKED", "NEEDS_ACTION"}
        for requirement in requirements
    )
    return TechnicianPilotReadiness(
        ready=blocking == 0,
        blocking_count=blocking,
        requirements=requirements,
    )


def summary(
    technician: Technician,
    settings: Settings | None = None,
    google_connection: CalendarConnection | None = None,
) -> TechnicianSummary:
    assignment = next(
        (item for item in technician.assignments if item.is_active and item.calendar is not None),
        None,
    )
    telegram, gps = technician.telegram, technician.gps
    calendar = (
        CalendarSummary(
            id=assignment.calendar.id,
            name=assignment.calendar.name,
            source=assignment.calendar.source,
            availability=assignment.calendar.availability,
        )
        if assignment
        else None
    )
    integrations = IntegrationSummary(
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
    )
    return TechnicianSummary(
        id=technician.id,
        first_name=technician.first_name,
        last_name=technician.last_name,
        status=technician.status,
        record_version=technician.record_version,
        accounting_timezone=technician.accounting_timezone,
        calendar=calendar,
        integrations=integrations,
        pilot_readiness=pilot_readiness(
            technician, calendar, integrations, settings, google_connection
        ),
        created_at=technician.created_at,
        updated_at=technician.updated_at,
    )


def detail(
    technician: Technician,
    settings: Settings | None = None,
    google_connection: CalendarConnection | None = None,
) -> TechnicianDetail:
    return TechnicianDetail(**summary(technician, settings, google_connection).model_dump())
