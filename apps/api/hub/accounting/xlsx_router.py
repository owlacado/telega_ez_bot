import logging
import time
from datetime import date as Date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from hub.accounting.domain import shift
from hub.accounting.router import Selector, reject_duplicate_selector
from hub.accounting.service import calculate, calculate_all_weekly
from hub.accounting.xlsx import (
    XLSX_CONTENT_TYPE,
    WeeklyAccountingXlsxModel,
    all_tech_filename,
    individual_filename,
    render_all_tech_weekly_xlsx,
    render_individual_weekly_xlsx,
)
from hub.core.database import session

logger = logging.getLogger(__name__)
technician_router = APIRouter(
    prefix="/api/technicians/{technician_id}/accounting", tags=["accounting"]
)
all_router = APIRouter(prefix="/api/accounting", tags=["accounting"])


class ExportSelector(Selector):
    week_start: Date


def validate_week(request: Request, week_start: Date) -> None:
    reject_duplicate_selector(request, "week_start")
    if week_start.weekday() != 0 or shift(week_start, 6) is None:
        raise HTTPException(422, "week_start must be a Monday with seven representable dates.")


def workbook_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@technician_router.get(
    "/weekly.xlsx",
    response_class=Response,
    responses={
        200: {"content": {XLSX_CONTENT_TYPE: {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def individual_weekly_xlsx(
    request: Request,
    technician_id: UUID,
    query: Annotated[ExportSelector, Query()],
    db: AsyncSession = Depends(session),
) -> Response:
    validate_week(request, query.week_start)
    started = time.perf_counter()
    accounting = await calculate(db, technician_id, "weekly", query.week_start)
    model = WeeklyAccountingXlsxModel.from_accounting(accounting)
    content = await run_in_threadpool(render_individual_weekly_xlsx, model)
    logger.info(
        "accounting_xlsx export=individual technician_id=%s week_start=%s "
        "technician_count=1 duration_ms=%d size=%d result=SUCCESS",
        technician_id,
        query.week_start,
        round((time.perf_counter() - started) * 1000),
        len(content),
    )
    return workbook_response(content, individual_filename(model))


@all_router.get(
    "/weekly/all.xlsx",
    response_class=Response,
    responses={
        200: {"content": {XLSX_CONTENT_TYPE: {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def all_tech_weekly_xlsx(
    request: Request,
    query: Annotated[ExportSelector, Query()],
    db: AsyncSession = Depends(session),
) -> Response:
    validate_week(request, query.week_start)
    started = time.perf_counter()
    accounting = await calculate_all_weekly(db, query.week_start)
    models = tuple(WeeklyAccountingXlsxModel.from_accounting(item) for item in accounting)
    content = await run_in_threadpool(render_all_tech_weekly_xlsx, models, query.week_start)
    week_end = shift(query.week_start, 6)
    logger.info(
        "accounting_xlsx export=all_tech week_start=%s technician_count=%d "
        "duration_ms=%d size=%d result=SUCCESS",
        query.week_start,
        len(models),
        round((time.perf_counter() - started) * 1000),
        len(content),
    )
    return workbook_response(content, all_tech_filename(query.week_start, week_end))
