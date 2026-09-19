"""Bounded reads in one PostgreSQL MVCC snapshot; never lock business rows."""

from datetime import date
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hub.accounting.domain import (
    AccountingContext,
    CurrentAccounting,
    ExpenseFact,
    ReportFact,
    build_daily,
    build_weekly,
    local_today,
    monday,
    shift,
)
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.technicians.models import Technician
from hub.work_reports.models import WorkReport, WorkReportRevision


def current_statement(parent, revision, technician_id, start, end):
    owner = revision.report_id if parent is WorkReport else revision.expense_id
    current = (
        select(revision)
        .where(and_(owner == parent.id, revision.revision_number == parent.current_revision_number))
        .correlate(parent)
        .limit(1)
        .lateral()
    )
    row = aliased(revision, current)
    day = row.operational_date if parent is WorkReport else row.expense_date
    # Outer join detects broken pointers rather than silently dropping canonical parents.
    return (
        select(parent.id, row)
        .outerjoin(row, true())
        .where(
            parent.technician_id == technician_id, or_(day.between(start, end), row.id.is_(None))
        )
    )


async def facts(db, technician_id, start, end):
    reports = []
    expenses = []
    for identifier, r in await db.execute(
        current_statement(WorkReport, WorkReportRevision, technician_id, start, end)
    ):
        if r is None:
            raise ValueError("Missing current report revision.")
        reports.append(
            ReportFact(
                id=identifier,
                revision_number=r.revision_number,
                business_date=r.operational_date,
                sequence=r.sequence,
                start_time=r.start_time,
                end_time=r.end_time,
                title=r.title,
                location=r.location,
                comments=r.comments,
                amount=r.amount_closed,
                payment_method=r.payment_method,
                closed_by=r.closed_by,
                google_reviews=r.google_reviews,
                groupon_reviews=r.groupon_reviews,
                facebook_reviews=r.facebook_reviews,
                maintenance=r.yearly_maintenance_plan_provided,
                submitted_at=r.submitted_at,
            )
        )
    for identifier, e in await db.execute(
        current_statement(TechnicianExpense, ExpenseRevision, technician_id, start, end)
    ):
        if e is None:
            raise ValueError("Missing current expense revision.")
        expenses.append(
            ExpenseFact(
                id=identifier,
                revision_number=e.revision_number,
                business_date=e.expense_date,
                accounting_timezone=e.accounting_timezone,
                expense_type=e.expense_type,
                amount=e.amount,
                note=e.note,
                submitted_at=e.submitted_at,
            )
        )
    return tuple(reports), tuple(expenses)


async def calculate(db: AsyncSession, technician_id: UUID, kind: str, selector: date | None = None):
    # Must be the first statement of a fresh session. Auth uses its own session.
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    result = (
        await db.execute(
            select(
                Technician.id,
                Technician.first_name,
                Technician.last_name,
                Technician.accounting_timezone,
                func.transaction_timestamp(),
            ).where(Technician.id == technician_id)
        )
    ).first()
    if result is None:
        raise HTTPException(404, "Technician not found.")
    tech_id, first_name, last_name, zone, instant = result
    try:
        today = local_today(instant, zone)
        context = AccountingContext(
            technician_id=tech_id,
            technician_name=f"{first_name} {last_name}".strip(),
            accounting_timezone=zone,
            setup_required=today is None,
            today=today,
            calculated_at=instant,
        )
        if selector is None and today is None:
            if kind == "current":
                return CurrentAccounting(**context.model_dump(), daily=None, weekly=None)
            raise HTTPException(
                409, "Configure accounting timezone or select an explicit historical date."
            )
        selected = selector or today
        start = selected if kind == "daily" else monday(selected)
        end = start if kind == "daily" else shift(start, 6)
        if end is None:
            raise HTTPException(422, "Choose a week with seven representable dates.")
        reports, expenses = await facts(db, technician_id, start, end)
        if kind == "daily":
            return build_daily(context, start, reports, expenses)
        week = build_weekly(context, start, reports, expenses)
        if kind == "weekly":
            return week
        return CurrentAccounting(
            **context.model_dump(),
            daily=next(d for d in week.days if d.business_date == today),
            weekly=week,
        )
    except (ValueError, ValidationError, KeyError) as exc:
        # Never include row contents, driver values or validation input in logs/errors.
        raise HTTPException(503, "Accounting facts require integrity review.") from exc
