import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.concurrency import run_in_threadpool

import hub.models  # noqa: F401
from hub.auth.middleware import install_auth
from hub.auth.router import router as auth_router
from hub.auth.security import password_hasher, random_token
from hub.calendar_events.router import router as events_router
from hub.calendars.router import router as calendars_router
from hub.core.config import Settings
from hub.core.database import session
from hub.core.errors import install_error_handlers
from hub.google_calendar.router import router as google_router
from hub.schedule_delivery.router import router as schedule_router
from hub.technicians.router import router as technicians_router
from hub.telegram.router import router as telegram_router


class Health(BaseModel):
    status: str
    database: str


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_async_engine(config.database_url, pool_pre_ping=True, hide_parameters=True)
        app.state.engine = engine
        # Google lock owners must not consume transaction-pool capacity across HTTP.
        google_lock_engine = create_async_engine(
            config.database_url, poolclass=NullPool, hide_parameters=True
        )
        app.state.google_lock_engine = google_lock_engine
        app.state.settings = config
        app.state.google_provider = None
        if config.google_mode == "real":
            from hub.google_calendar.provider import GoogleCalendarProvider

            app.state.google_provider = GoogleCalendarProvider(config)
        elif config.google_mode == "fake":
            from hub.google_calendar.fake import FakeCalendarProvider

            app.state.google_provider = FakeCalendarProvider()
        app.state.dummy_password_hash = await run_in_threadpool(
            password_hasher().hash, random_token()
        )
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        yield
        await google_lock_engine.dispose()
        await engine.dispose()

    app = FastAPI(title="Technician Hub API", version="0.2.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(telegram_router)
    install_auth(app, config)
    app.include_router(technicians_router)
    app.include_router(calendars_router)
    app.include_router(google_router)
    app.include_router(events_router)
    app.include_router(schedule_router)

    @app.middleware("http")
    async def protect_responses(request: Request, call_next):
        callback = request.url.path == "/api/calendar-connections/google/callback"
        if callback:
            request.state.google_callback = request.query_params.multi_items()
            # Uvicorn logs scope after response: remove secrets before any downstream handler.
            request.scope["query_string"] = b""
        try:
            response = await call_next(request)
        except Exception:
            if "calendar-events" not in getattr(request.scope.get("route"), "tags", ()):
                raise
            # Unexpected schedule failures must retain privacy headers too. Never
            # serialize/log the exception, whose arguments can contain provider PII.
            from starlette.responses import JSONResponse

            logging.getLogger("hub.calendar_events.service").error(
                "calendar_events result=INTERNAL_ERROR"
            )
            response = JSONResponse(
                {"error": {"code": "internal_error", "message": "Unable to read schedule."}},
                status_code=500,
            )
        if callback and response.status_code in {401, 403}:
            from starlette.responses import RedirectResponse

            response = RedirectResponse("/calendars?google=error", status_code=303)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health", response_model=Health, tags=["health"])
    async def health(db: AsyncSession = Depends(session)) -> Health:
        await db.execute(text("SELECT 1"))
        return Health(status="ok", database="connected")

    return app


app = create_app()
