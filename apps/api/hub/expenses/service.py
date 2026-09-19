"""Expense facts, serialized on the shared technician/binding/session lock boundary."""

import json
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select, true
from sqlalchemy.orm import aliased

from hub.audit.service import audit
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.expenses.schemas import ExpenseForm, ExpenseList, ExpenseRead, ExpenseReceipt
from hub.work_reports import service as forms


def local_date(instant, zone):
    if not zone:
        raise HTTPException(
            409,
            "Ask your manager to configure your accounting timezone before submitting expenses.",
        )
    return instant.astimezone(ZoneInfo(zone)).date()


async def issue(db, event, bot_id, settings):
    return await forms.issue(db, event, bot_id, settings, purpose="EXPENSE")


async def open_form(factory, token):
    async with factory() as db, db.begin():
        value, tech = await forms.authorize(db, token, purpose="EXPENSE")
        if value.status == "SUBMITTED":
            row = (
                await db.execute(current_expenses().where(TechnicianExpense.id == value.expense_id))
            ).one()
            zone, day = row[1].accounting_timezone, row[1].expense_date
        else:
            zone = tech.accounting_timezone
            day = local_date(await forms.database_now(db), zone)
        return ExpenseForm(
            status=value.status,
            expires_at=value.expires_at,
            technician_name=f"{tech.first_name} {tech.last_name}",
            accounting_timezone=zone,
            expense_date=day,
            expense_id=value.expense_id,
        )


async def submit(factory, token, payload):
    fingerprint = forms.digest(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    )
    async with factory() as db, db.begin():
        value, tech = await forms.authorize(db, token, purpose="EXPENSE")
        if value.status == "SUBMITTED":
            if value.payload_hash != fingerprint:
                raise HTTPException(409, "FORM_ALREADY_SUBMITTED")
            return ExpenseReceipt(expense_id=value.expense_id)
        instant = await forms.database_now(db)
        if instant >= value.expires_at:
            forms.unavailable()
        day = local_date(instant, tech.accounting_timezone)
        expense = TechnicianExpense(id=uuid4(), technician_id=tech.id)
        db.add(expense)
        await db.flush()
        db.add(
            ExpenseRevision(
                expense_id=expense.id,
                revision_number=1,
                technician_name=f"{tech.first_name} {tech.last_name}",
                expense_date=day,
                accounting_timezone=tech.accounting_timezone,
                submitted_at=instant,
                **payload.model_dump(),
            )
        )
        value.status = "SUBMITTED"
        value.expense_id = expense.id
        value.payload_hash = fingerprint
        value.submitted_at = instant
        audit(db, "expense.submitted", expense.id, actor_kind="TECHNICIAN")
        return ExpenseReceipt(expense_id=expense.id)


def current_expenses():
    # The unique (expense_id, revision_number) lookup is bounded per parent.
    # A lateral LIMIT also prevents stale statistics after bulk intake from
    # choosing a nested-loop full history scan for every expense.
    revision = aliased(
        ExpenseRevision,
        select(ExpenseRevision)
        .where(
            (ExpenseRevision.expense_id == TechnicianExpense.id)
            & (ExpenseRevision.revision_number == TechnicianExpense.current_revision_number)
        )
        .correlate(TechnicianExpense)
        .limit(1)
        .lateral(),
    )
    return select(TechnicianExpense, revision).join(revision, true())


def expense_view(expense, revision):
    fields = {
        key: getattr(revision, key)
        for key in (
            "technician_name",
            "expense_date",
            "accounting_timezone",
            "expense_type",
            "amount",
            "note",
            "revision_number",
            "submitted_at",
        )
    }
    return ExpenseRead(id=expense.id, technician_id=expense.technician_id, **fields)


async def list_expenses(db, tech, limit):
    # One statement gives list and total a coherent MVCC snapshot during submission.
    day = (
        local_date(await forms.database_now(db), tech.accounting_timezone)
        if tech.accounting_timezone
        else None
    )
    current = (
        current_expenses()
        .where(TechnicianExpense.technician_id == tech.id)
        .cte("current_expense_facts")
        .prefix_with("MATERIALIZED")
    )
    summary = (
        select(
            func.coalesce(func.sum(current.c.amount), 0).label("total"), func.count().label("count")
        )
        .where(current.c.expense_date == day)
        .subquery()
    )
    recent = (
        select(current)
        .order_by(current.c.submitted_at.desc(), current.c.id)
        .limit(limit)
        .subquery()
    )
    rows = (
        (await db.execute(select(summary, recent).select_from(summary.outerjoin(recent, true()))))
        .mappings()
        .all()
    )
    expenses = [
        ExpenseRead(
            id=r["id"],
            technician_id=tech.id,
            **{
                k: r[k]
                for k in (
                    "technician_name",
                    "expense_date",
                    "accounting_timezone",
                    "expense_type",
                    "amount",
                    "note",
                    "revision_number",
                    "submitted_at",
                )
            },
        )
        for r in rows
        if r["id"]
    ]
    return ExpenseList(
        expenses=expenses,
        limit=limit,
        today=day,
        accounting_timezone=tech.accounting_timezone,
        today_total=rows[0]["total"] if day else Decimal("0.00"),
        today_count=rows[0]["count"] if day else 0,
    )
