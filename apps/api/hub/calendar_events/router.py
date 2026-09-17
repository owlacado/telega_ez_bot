from uuid import UUID

from fastapi import APIRouter, Request, Response

from hub.calendar_events.schemas import ScheduleRead
from hub.calendar_events.service import read_schedule

router = APIRouter(prefix="/api/technicians", tags=["calendar-events"])


@router.get("/{technician_id}/calendar/today", response_model=ScheduleRead)
async def today(technician_id: UUID, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await read_schedule(request, technician_id)


@router.get("/{technician_id}/calendar/next-schedule", response_model=ScheduleRead)
async def next_schedule(technician_id: UUID, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await read_schedule(request, technician_id, preview=True)
