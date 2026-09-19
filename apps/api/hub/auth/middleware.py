import hmac
import json

from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from hub.auth.models import Manager, ManagerSession
from hub.auth.security import csrf_for, digest, now
from hub.core.config import Settings
from hub.work_reports.router import FORM_PATHS

COOKIE_NAME = "hub_session"
PUBLIC_PATHS = {"/api/health", "/api/auth/login"}


def failure(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


def install_auth(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            return failure(403, "origin_rejected", "This origin is not allowed.")
        if mutation and (not origin or origin not in settings.allowed_origins):
            return failure(403, "origin_required", "A trusted Origin header is required.")
        if request.method == "OPTIONS":
            return failure(403, "cors_disabled", "Cross-origin API access is disabled.")
        if request.url.path in FORM_PATHS:
            if request.method != "POST" or request.headers.get("x-hub-request") != "1":
                return failure(403, "form_request_required", "Open the secure report form.")
            # Enforce a bounded body even when Content-Length is absent/chunked.
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 32768:
                    return failure(413, "body_too_large", "Report input is too large.")
                body.extend(chunk)
            request._body = bytes(body)

            def unique_fields(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Repeated field")
                    result[key] = value
                return result

            try:
                json.loads(body or b"{}", object_pairs_hook=unique_fields)
            except (ValueError, UnicodeError, RecursionError):
                return failure(422, "invalid_form", "Use a valid report with no repeated fields.")
            return await call_next(request)
        if request.url.path in PUBLIC_PATHS:
            if (
                request.url.path == "/api/auth/login"
                and request.method == "POST"
                and request.headers.get("x-hub-request") != "1"
            ):
                return failure(
                    403, "csrf_rejected", "A same-origin application request is required."
                )
            return await call_next(request)
        token = request.cookies.get(COOKIE_NAME, "")
        if not token or len(token) > 128:
            return failure(401, "unauthenticated", "Sign in to continue.")
        try:
            async with request.app.state.session_factory() as db:
                row = (
                    await db.execute(
                        select(Manager, ManagerSession)
                        .join(ManagerSession, ManagerSession.manager_id == Manager.id)
                        .where(
                            ManagerSession.token_hash == digest(token),
                            ManagerSession.revoked_at.is_(None),
                            ManagerSession.expires_at > now(),
                            Manager.is_active.is_(True),
                        )
                    )
                ).first()
        except (SQLAlchemyError, OSError):
            return failure(503, "unavailable", "The database is unavailable. Try again shortly.")
        if not row:
            return failure(401, "unauthenticated", "Sign in to continue.")
        manager, record = row
        if mutation and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), csrf_for(token)
        ):
            return failure(403, "csrf_rejected", "Refresh your session and try again.")
        request.state.manager_id = manager.id
        request.state.manager_username = manager.username
        request.state.session_id = record.id
        request.state.session_expires_at = record.expires_at
        return await call_next(request)
