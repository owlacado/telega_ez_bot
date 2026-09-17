from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import RedirectResponse

from hub.auth.middleware import COOKIE_NAME
from hub.auth.security import now
from hub.core.database import session
from hub.google_calendar import service
from hub.google_calendar.schemas import (
    AuthorizationRead,
    DisconnectInput,
    GoogleConnectionRead,
    ScanRead,
    StartInput,
)

router = APIRouter(prefix="/api/calendar-connections/google", tags=["google-calendar"])


@router.get("", response_model=GoogleConnectionRead)
async def connection_status(request: Request, db: AsyncSession = Depends(session)):
    return await service.status(request, db)


@router.post("/start", response_model=AuthorizationRead)
async def start(
    request: Request, payload: StartInput, response: Response, db: AsyncSession = Depends(session)
):
    authorization_url = await service.start(request, db, payload)
    # A Strict cookie is withheld on the cross-site top-level Google callback.
    # Reissue the SAME authenticated session as Lax without extending its expiry.
    # POST origin/CSRF checks and callback state/session binding remain mandatory.
    response.set_cookie(
        COOKIE_NAME,
        request.cookies[COOKIE_NAME],
        max_age=max(0, int((request.state.session_expires_at - now()).total_seconds())),
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return AuthorizationRead(authorization_url=authorization_url)


@router.get("/callback", include_in_schema=False)
async def callback(request: Request):
    success = await service.callback(request)
    return RedirectResponse(
        "/calendars?google=" + ("connected" if success else "error"),
        status_code=303,
        headers={"Referrer-Policy": "no-referrer"},
    )


@router.post("/scan", response_model=ScanRead)
async def scan(request: Request):
    return ScanRead(discovered=await service.scan(request))


@router.post("/disconnect", status_code=204)
async def disconnect(request: Request, payload: DisconnectInput):
    await service.disconnect(request, payload)
    return Response(status_code=204)
