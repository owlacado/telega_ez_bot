from uuid import UUID

from fastapi import APIRouter, Request

from hub.schedule_delivery.schemas import (
    DeliverySettingInput,
    DispatchRead,
    ScheduleDeliveryRead,
    SendSchedule,
)
from hub.schedule_delivery.service import create_dispatch, read_delivery, set_enabled

router = APIRouter(prefix="/api/technicians", tags=["calendar-events", "schedule-delivery"])


@router.get("/{technician_id}/schedule-delivery", response_model=ScheduleDeliveryRead)
async def history(technician_id: UUID, request: Request):
    return await read_delivery(request, technician_id)


@router.put("/{technician_id}/schedule-delivery", response_model=ScheduleDeliveryRead)
async def configure(technician_id: UUID, body: DeliverySettingInput, request: Request):
    return await set_enabled(request, technician_id, body.enabled)


@router.post("/{technician_id}/schedule-dispatches", response_model=DispatchRead, status_code=202)
async def send(technician_id: UUID, body: SendSchedule, request: Request):
    return await create_dispatch(request, technician_id, body)
