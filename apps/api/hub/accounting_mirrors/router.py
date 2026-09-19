from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.accounting.router import reject_duplicate_selector
from hub.accounting_mirrors import service
from hub.accounting_mirrors.models import AccountingMirrorWorkerState
from hub.accounting_mirrors.schemas import (
    MirrorActionInput,
    MirrorConfigureInput,
    MirrorStatusRead,
    MirrorWorkerHealthRead,
)
from hub.core.database import session

technician_router = APIRouter(
    prefix="/api/technicians/{technician_id}/accounting/mirror",
    tags=["accounting-mirrors"],
)
all_router = APIRouter(prefix="/api/accounting/weekly/all/mirror", tags=["accounting-mirrors"])
health_router = APIRouter(prefix="/api/accounting/mirror-worker", tags=["accounting-mirrors"])


def checked_week(request: Request, week_start: date) -> date:
    reject_duplicate_selector(request, "week_start")
    service.validate_week(week_start)
    return week_start


@technician_router.get("", response_model=MirrorStatusRead)
async def individual_status(
    request: Request,
    technician_id: UUID,
    week_start: Annotated[date, Query()],
    db: AsyncSession = Depends(session),
):
    return await service.status(
        db,
        kind="INDIVIDUAL",
        technician_id=technician_id,
        week_start=checked_week(request, week_start),
    )


@technician_router.put("", response_model=MirrorStatusRead)
async def configure_individual(
    request: Request,
    technician_id: UUID,
    week_start: Annotated[date, Query()],
    payload: MirrorConfigureInput,
    db: AsyncSession = Depends(session),
):
    week = checked_week(request, week_start)
    await service.configure(
        db,
        kind="INDIVIDUAL",
        technician_id=technician_id,
        spreadsheet=payload.spreadsheet,
        replace=payload.replace,
        manager_id=request.state.manager_id,
    )
    await db.commit()
    return await service.status(db, kind="INDIVIDUAL", technician_id=technician_id, week_start=week)


@technician_router.post("/action", response_model=MirrorStatusRead)
async def individual_action(
    request: Request,
    technician_id: UUID,
    week_start: Annotated[date, Query()],
    payload: MirrorActionInput,
    db: AsyncSession = Depends(session),
):
    week = checked_week(request, week_start)
    await service.action(
        db,
        kind="INDIVIDUAL",
        technician_id=technician_id,
        week_start=week,
        requested_action=payload.action,
        expected_generation=payload.expected_generation,
        manager_id=request.state.manager_id,
    )
    await db.commit()
    return await service.status(db, kind="INDIVIDUAL", technician_id=technician_id, week_start=week)


@all_router.get("", response_model=MirrorStatusRead)
async def all_status(
    request: Request,
    week_start: Annotated[date, Query()],
    db: AsyncSession = Depends(session),
):
    return await service.status(
        db,
        kind="ALL_TECH",
        technician_id=None,
        week_start=checked_week(request, week_start),
    )


@all_router.put("", response_model=MirrorStatusRead)
async def configure_all(
    request: Request,
    week_start: Annotated[date, Query()],
    payload: MirrorConfigureInput,
    db: AsyncSession = Depends(session),
):
    week = checked_week(request, week_start)
    await service.configure(
        db,
        kind="ALL_TECH",
        technician_id=None,
        spreadsheet=payload.spreadsheet,
        replace=payload.replace,
        manager_id=request.state.manager_id,
    )
    await db.commit()
    return await service.status(db, kind="ALL_TECH", technician_id=None, week_start=week)


@all_router.post("/action", response_model=MirrorStatusRead)
async def all_action(
    request: Request,
    week_start: Annotated[date, Query()],
    payload: MirrorActionInput,
    db: AsyncSession = Depends(session),
):
    week = checked_week(request, week_start)
    await service.action(
        db,
        kind="ALL_TECH",
        technician_id=None,
        week_start=week,
        requested_action=payload.action,
        expected_generation=payload.expected_generation,
        manager_id=request.state.manager_id,
    )
    await db.commit()
    return await service.status(db, kind="ALL_TECH", technician_id=None, week_start=week)


@health_router.get("/health", response_model=MirrorWorkerHealthRead)
async def worker_health(db: AsyncSession = Depends(session)):
    state = await service.worker_state(db)
    running = await db.scalar(
        select(func.count())
        .select_from(AccountingMirrorWorkerState)
        .where(
            AccountingMirrorWorkerState.status == "RUNNING",
            AccountingMirrorWorkerState.heartbeat_at
            >= func.clock_timestamp() - timedelta(seconds=120),
        )
    )
    return MirrorWorkerHealthRead(state=state, running_instances=running or 0)
