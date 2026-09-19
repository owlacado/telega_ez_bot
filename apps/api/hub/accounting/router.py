import re
from datetime import date as Date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from hub.accounting.domain import CurrentAccounting, DailyAccounting, WeeklyAccounting, shift
from hub.accounting.service import calculate
from hub.core.database import session

router = APIRouter(prefix="/api/technicians/{technician_id}/accounting", tags=["accounting"])


class Selector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def iso_date(cls, value):
        if value is not None and (
            not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)
        ):
            raise ValueError("Use YYYY-MM-DD.")
        return value


class DailySelector(Selector):
    date: Date | None = None


class WeeklySelector(Selector):
    week_start: Date | None = None


class CurrentSelector(Selector):
    pass


def reject_duplicate_selector(request: Request, name: str) -> None:
    if len(request.query_params.getlist(name)) > 1:
        raise HTTPException(422, f"{name} must be supplied at most once.")


@router.get("/daily", response_model=DailyAccounting)
async def daily(
    request: Request,
    technician_id: UUID,
    query: Annotated[DailySelector, Query()],
    db: AsyncSession = Depends(session),
):
    reject_duplicate_selector(request, "date")
    return await calculate(db, technician_id, "daily", query.date)


@router.get("/weekly", response_model=WeeklyAccounting)
async def weekly(
    request: Request,
    technician_id: UUID,
    query: Annotated[WeeklySelector, Query()],
    db: AsyncSession = Depends(session),
):
    reject_duplicate_selector(request, "week_start")
    if query.week_start and (query.week_start.weekday() != 0 or shift(query.week_start, 6) is None):
        raise HTTPException(422, "week_start must be a Monday with seven representable dates.")
    return await calculate(db, technician_id, "weekly", query.week_start)


@router.get("/current", response_model=CurrentAccounting)
async def current(
    technician_id: UUID,
    query: Annotated[CurrentSelector, Query()],
    db: AsyncSession = Depends(session),
):
    return await calculate(db, technician_id, "current")
