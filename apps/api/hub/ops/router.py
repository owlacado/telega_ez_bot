from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hub.core.database import session
from hub.ops.schemas import OperationsHealth
from hub.ops.service import operations_health

router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.get("/health", response_model=OperationsHealth)
async def health(request: Request, db: AsyncSession = Depends(session)) -> OperationsHealth:
    return await operations_health(db, request.app.state.settings)
