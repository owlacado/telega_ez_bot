"""Bounded reads in one PostgreSQL MVCC snapshot; never lock business rows."""

from collections import defaultdict
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
    WeeklyAccounting,
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
    current, row = current_revision(parent, revision)
    day = row.operational_date if parent is WorkReport else row.expense_date
    # Outer join detects broken pointers rather than silently dropping canonical parents.
    return (
        select(parent.id, row)
        .outerjoin(row, true())
        .where(
            parent.technician_id == technician_id, or_(day.between(start, end), row.id.is_(None))
        )
    )


def current_revision(parent, revision):
    owner = revision.report_id if parent is WorkReport else revision.expense_id
    current = (
        select(revision)
        .where(and_(owner == parent.id, revision.revision_number == parent.current_revision_number))
        .correlate(parent)
        .limit(1)
        .lateral()
    )
    row = aliased(revision, current)
    return current, row


def all_current_statement(parent, revision, start, end):
    current, row = current_revision(parent, revision)
    day = row.operational_date if parent is WorkReport else row.expense_date
    return (
        select(parent.technician_id, parent.id, row)
        .outerjoin(row, true())
        .where(or_(day.between(start, end), row.id.is_(None)))
    )


def report_fact(identifier, revision):
    return ReportFact(
        id=identifier,
        revision_number=revision.revision_number,
        business_date=revision.operational_date,
        sequence=revision.sequence,
        start_time=revision.start_time,
        end_time=revision.end_time,
        title=revision.title,
        location=revision.location,
        comments=revision.comments,
        amount=revision.amount_closed,
        payment_method=revision.payment_method,
        closed_by=revision.closed_by,
        google_reviews=revision.google_reviews,
        groupon_reviews=revision.groupon_reviews,
        facebook_reviews=revision.facebook_reviews,
        maintenance=revision.yearly_maintenance_plan_provided,
        submitted_at=revision.submitted_at,
    )


def expense_fact(identifier, revision):
    return ExpenseFact(
        id=identifier,
        revision_number=revision.revision_number,
        business_date=revision.expense_date,
        accounting_timezone=revision.accounting_timezone,
        expense_type=revision.expense_type,
        amount=revision.amount,
        note=revision.note,
        submitted_at=revision.submitted_at,
    )


async def facts(db, technician_id, start, end):
    reports = []
    expenses = []
    for identifier, r in await db.execute(
        current_statement(WorkReport, WorkReportRevision, technician_id, start, end)
    ):
        if r is None:
            raise ValueError("Missing current report revision.")
        reports.append(report_fact(identifier, r))
    for identifier, e in await db.execute(
        current_statement(TechnicianExpense, ExpenseRevision, technician_id, start, end)
    ):
        if e is None:
            raise ValueError("Missing current expense revision.")
        expenses.append(expense_fact(identifier, e))
    return tuple(reports), tuple(expenses)


async def all_facts(db, start, end):
    reports = defaultdict(list)
    expenses = defaultdict(list)
    for technician_id, identifier, revision in await db.execute(
        all_current_statement(WorkReport, WorkReportRevision, start, end)
    ):
        if revision is None:
            raise ValueError("Missing current report revision.")
        reports[technician_id].append(report_fact(identifier, revision))
    for technician_id, identifier, revision in await db.execute(
        all_current_statement(TechnicianExpense, ExpenseRevision, start, end)
    ):
        if revision is None:
            raise ValueError("Missing current expense revision.")
        expenses[technician_id].append(expense_fact(identifier, revision))
    return reports, expenses


async def calculate_all_weekly(db: AsyncSession, start: date) -> tuple[WeeklyAccounting, ...]:
    """Build every included technician from one coherent PostgreSQL snapshot."""
    if start.weekday() != 0 or shift(start, 6) is None:
        raise HTTPException(422, "week_start must be a Monday with seven representable dates.")
    end = shift(start, 6)
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    technicians = (
        await db.execute(
            select(
                Technician.id,
                Technician.first_name,
                Technician.last_name,
                Technician.accounting_timezone,
                Technician.status,
                Technician.created_at,
                func.transaction_timestamp(),
            )
        )
    ).all()
    technicians = sorted(
        technicians,
        key=lambda item: (f"{item.first_name} {item.last_name}".strip().casefold(), str(item.id)),
    )
    try:
        reports, expenses = await all_facts(db, start, end)
        result = []
        for technician_id, first_name, last_name, zone, status, created_at, instant in technicians:
            technician_reports = tuple(reports[technician_id])
            technician_expenses = tuple(expenses[technician_id])
            has_facts = bool(technician_reports or technician_expenses)
            active_during_week = status == "ACTIVE" and created_at.date() <= end
            if not active_during_week and not has_facts:
                continue
            today = local_today(instant, zone)
            context = AccountingContext(
                technician_id=technician_id,
                technician_name=f"{first_name} {last_name}".strip(),
                accounting_timezone=zone,
                setup_required=today is None,
                today=today,
                calculated_at=instant,
            )
            result.append(build_weekly(context, start, technician_reports, technician_expenses))
        return tuple(result)
    except (ValueError, ValidationError, KeyError) as exc:
        raise HTTPException(503, "Accounting facts require integrity review.") from exc


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
