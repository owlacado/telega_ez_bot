from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from hub.core.database import session
from hub.telegram import bindings, invitations
from hub.telegram.locks import advisory_guard
from hub.telegram.schemas import (
    DeliveryRead,
    Disconnect,
    IssuedInvitation,
    IssueInvitation,
    ReviewInvitation,
    RuntimeRead,
    TelegramState,
    TestMessage,
)
from hub.telegram.state import read_state, runtime_state

router = APIRouter(prefix="/api", tags=["Telegram onboarding"])


@router.get("/telegram/runtime", response_model=RuntimeRead)
async def runtime(request: Request, db: AsyncSession = Depends(session)) -> RuntimeRead:
    return await runtime_state(db, request.app.state.settings)


@router.get("/technicians/{identifier}/telegram", response_model=TelegramState)
async def state(
    identifier: UUID, request: Request, db: AsyncSession = Depends(session)
) -> TelegramState:
    return await read_state(db, identifier, request.app.state.settings)


@router.post(
    "/technicians/{identifier}/telegram/invitations",
    response_model=IssuedInvitation,
    status_code=201,
)
async def issue(
    identifier: UUID,
    payload: IssueInvitation,
    request: Request,
    db: AsyncSession = Depends(session),
) -> IssuedInvitation:
    return await invitations.issue(
        db, identifier, request.state.manager_id, payload, request.app.state.settings
    )


@router.post(
    "/technicians/{identifier}/telegram/invitations/{invitation_id}/revoke", status_code=204
)
async def revoke(
    identifier: UUID, invitation_id: UUID, request: Request, db: AsyncSession = Depends(session)
) -> Response:
    await invitations.revoke(db, identifier, invitation_id, request.state.manager_id)
    return Response(status_code=204)


@router.post(
    "/technicians/{identifier}/telegram/invitations/{invitation_id}/review", status_code=204
)
async def review(
    identifier: UUID,
    invitation_id: UUID,
    payload: ReviewInvitation,
    request: Request,
    db: AsyncSession = Depends(session),
) -> Response:
    async with advisory_guard(request.app.state.engine, "technician", identifier):
        await bindings.review(
            db,
            identifier,
            invitation_id,
            request.state.manager_id,
            payload,
            request.app.state.settings,
        )
    return Response(status_code=204)


@router.post(
    "/technicians/{identifier}/telegram/invitations/{invitation_id}/retry", status_code=202
)
async def retry(
    identifier: UUID, invitation_id: UUID, request: Request, db: AsyncSession = Depends(session)
) -> dict[str, str]:
    await bindings.request_verification(
        db, identifier, invitation_id, request.state.manager_id, request.app.state.settings
    )
    return {"status": "QUEUED"}


@router.post("/technicians/{identifier}/telegram/disconnect", status_code=204)
async def disconnect(
    identifier: UUID, payload: Disconnect, request: Request, db: AsyncSession = Depends(session)
) -> Response:
    async with advisory_guard(request.app.state.engine, "technician", identifier):
        await bindings.disconnect(db, identifier, request.state.manager_id, payload)
    return Response(status_code=204)


@router.post(
    "/technicians/{identifier}/telegram/test-message", response_model=DeliveryRead, status_code=202
)
async def test_message(
    identifier: UUID, payload: TestMessage, request: Request, db: AsyncSession = Depends(session)
) -> DeliveryRead:
    job = await bindings.request_test(
        db, identifier, request.state.manager_id, payload, request.app.state.settings
    )
    return DeliveryRead(
        id=job.id,
        destination=job.destination,
        kind=job.kind,
        state=job.state,
        error_code=job.error_code,
        created_at=job.created_at,
    )
