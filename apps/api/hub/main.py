from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.concurrency import run_in_threadpool

import hub.models  # noqa: F401
from hub.auth.middleware import install_auth
from hub.auth.router import router as auth_router
from hub.auth.security import password_hasher, random_token
from hub.calendars.router import router as calendars_router
from hub.core.config import Settings
from hub.core.database import session
from hub.core.errors import install_error_handlers
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
        app.state.settings = config
        app.state.dummy_password_hash = await run_in_threadpool(
            password_hasher().hash, random_token()
        )
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        yield
        await engine.dispose()

    app = FastAPI(title="Technician Hub API", version="0.2.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(telegram_router)
    install_auth(app, config)
    app.include_router(technicians_router)
    app.include_router(calendars_router)

    @app.middleware("http")
    async def protect_responses(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health", response_model=Health, tags=["health"])
    async def health(db: AsyncSession = Depends(session)) -> Health:
        await db.execute(text("SELECT 1"))
        return Health(status="ok", database="connected")

    return app


app = create_app()
