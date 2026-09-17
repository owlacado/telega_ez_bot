from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.auth.middleware import COOKIE_NAME
from hub.auth.models import ManagerSession
from hub.auth.schemas import Login, ManagerRead
from hub.auth.security import csrf_for, now
from hub.auth.service import login
from hub.core.database import session

router = APIRouter(prefix="/api/auth", tags=["manager authentication"])


@router.post("/login", response_model=ManagerRead)
async def sign_in(
    payload: Login, request: Request, response: Response, db: AsyncSession = Depends(session)
) -> ManagerRead:
    settings = request.app.state.settings
    manager, record, token = await login(
        db,
        payload.username,
        payload.password,
        request.client.host if request.client else "unknown",
        settings,
        request.app.state.dummy_password_hash,
        request.cookies.get(COOKIE_NAME),
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_lifetime_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return ManagerRead(
        id=manager.id,
        username=manager.username,
        csrf_token=csrf_for(token),
        expires_at=record.expires_at,
    )


@router.get("/me", response_model=ManagerRead)
async def current_manager(request: Request) -> ManagerRead:
    return ManagerRead(
        id=request.state.manager_id,
        username=request.state.manager_username,
        csrf_token=csrf_for(request.cookies[COOKIE_NAME]),
        expires_at=request.state.session_expires_at,
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, db: AsyncSession = Depends(session)) -> Response:
    await db.execute(
        update(ManagerSession)
        .where(ManagerSession.id == request.state.session_id)
        .values(revoked_at=now())
    )
    audit(db, "auth.logout", request.state.manager_id, actor_id=request.state.manager_id)
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return response
