from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import hub.models  # noqa: F401
from hub.calendars.router import router as calendars_router
from hub.core.config import Settings
from hub.core.database import session
from hub.core.errors import install_error_handlers
from hub.technicians.router import router as technicians_router


class Health(BaseModel):
    status: str
    database: str


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_async_engine(config.database_url, pool_pre_ping=True)
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        yield
        await engine.dispose()

    app = FastAPI(title="Technician Hub API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
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
