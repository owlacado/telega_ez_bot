"""Canonical, renderer-independent accounting. Inputs are current immutable facts."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

PAYMENTS = ("CASH", "ZELLE", "CHECK", "CREDIT_CARD", "VENMO", "SUPER", "ESTIMATE", "CANCEL")
REVIEWS = ("GOOGLE", "GROUPON", "FACEBOOK")
CLOSERS = ("MYSELF", "CALL_CENTER")
Money = Annotated[
    Decimal,
    Field(strict=True, ge=0, allow_inf_nan=False),
    PlainSerializer(lambda v: format(v, ".2f"), return_type=str),
]


class Projection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ReportFact(Projection):
    id: UUID
    revision_number: int = Field(gt=0)
    business_date: date
    sequence: int = Field(gt=0)
    start_time: str
    end_time: str
    title: str
    location: str
    comments: str
    amount: Money
    payment_method: Literal[
        "CASH", "ZELLE", "CHECK", "CREDIT_CARD", "VENMO", "SUPER", "ESTIMATE", "CANCEL"
    ]
    closed_by: Literal["MYSELF", "CALL_CENTER"]
    google_reviews: int = Field(ge=0, le=100)
    groupon_reviews: int = Field(ge=0, le=100)
    facebook_reviews: int = Field(ge=0, le=100)
    maintenance: bool
    submitted_at: datetime

    @field_validator("amount")
    @classmethod
    def exact_money(cls, value):
        if value > Decimal("9999999999.99") or value.as_tuple().exponent < -2:
            raise ValueError("Invalid accounting money.")
        return value

    @model_validator(mode="after")
    def zero_outcome(self):
        if self.payment_method in {"ESTIMATE", "CANCEL"} and self.amount != 0:
            raise ValueError("Invalid zero outcome.")
        return self


class ExpenseFact(Projection):
    id: UUID
    revision_number: int = Field(gt=0)
    business_date: date
    accounting_timezone: str
    expense_type: str
    amount: Money
    note: str
    submitted_at: datetime

    @field_validator("amount")
    @classmethod
    def exact_money(cls, value):
        return ReportFact.exact_money(value)


class AccountingTotals(Projection):
    gross_total: Money
    expense_total: Money
    report_count: int
    expense_count: int
    maintenance_count: int
    payments: dict[str, Money]
    reviews: dict[str, int]
    closed_by: dict[str, int]


class AccountingContext(Projection):
    technician_id: UUID
    technician_name: str
    accounting_timezone: str | None
    setup_required: bool
    today: date | None
    calculated_at: datetime


class DailyAccounting(AccountingContext):
    business_date: date
    previous_date: date | None
    next_date: date | None
    reports: tuple[ReportFact, ...]
    expenses: tuple[ExpenseFact, ...]
    totals: AccountingTotals


class WeeklyAccounting(AccountingContext):
    week_start: date
    week_end: date
    previous_week: date | None
    next_week: date | None
    days: tuple[DailyAccounting, ...]
    totals: AccountingTotals


class CurrentAccounting(AccountingContext):
    daily: DailyAccounting | None
    weekly: WeeklyAccounting | None


def local_today(instant: datetime, zone: str | None) -> date | None:
    if not zone:
        return None
    return instant.astimezone(ZoneInfo(zone)).date()


def monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


def shift(value: date, days: int) -> date | None:
    try:
        return value + timedelta(days=days)
    except OverflowError:
        return None


def aggregate(
    reports: tuple[ReportFact, ...], expenses: tuple[ExpenseFact, ...]
) -> AccountingTotals:
    payments = {code: Decimal("0.00") for code in PAYMENTS}
    reviews = {code: 0 for code in REVIEWS}
    closers = {code: 0 for code in CLOSERS}
    for report in reports:
        payments[report.payment_method] += report.amount
        for code in REVIEWS:
            reviews[code] += getattr(report, code.lower() + "_reviews")
        closers[report.closed_by] += 1
    return AccountingTotals(
        gross_total=sum(payments.values(), Decimal("0.00")),
        expense_total=sum((e.amount for e in expenses), Decimal("0.00")),
        report_count=len(reports),
        expense_count=len(expenses),
        maintenance_count=sum(r.maintenance for r in reports),
        payments=payments,
        reviews=reviews,
        closed_by=closers,
    )


def build_daily(
    context: AccountingContext,
    day: date,
    reports: tuple[ReportFact, ...],
    expenses: tuple[ExpenseFact, ...],
) -> DailyAccounting:
    jobs = tuple(
        sorted(
            (r for r in reports if r.business_date == day),
            key=lambda r: (r.sequence, r.submitted_at, r.id),
        )
    )
    costs = tuple(
        sorted(
            (e for e in expenses if e.business_date == day), key=lambda e: (e.submitted_at, e.id)
        )
    )
    return DailyAccounting(
        **context.model_dump(),
        business_date=day,
        previous_date=shift(day, -1),
        next_date=shift(day, 1),
        reports=jobs,
        expenses=costs,
        totals=aggregate(jobs, costs),
    )


def build_weekly(
    context: AccountingContext,
    start: date,
    reports: tuple[ReportFact, ...],
    expenses: tuple[ExpenseFact, ...],
) -> WeeklyAccounting:
    if start.weekday() != 0 or shift(start, 6) is None:
        raise ValueError("Choose a Monday with seven representable dates.")
    days = tuple(
        build_daily(context, start + timedelta(days=i), reports, expenses) for i in range(7)
    )
    # Same arithmetic for both projections; weekly input is exactly the seven daily facts.
    return WeeklyAccounting(
        **context.model_dump(),
        week_start=start,
        week_end=start + timedelta(days=6),
        previous_week=shift(start, -7),
        next_week=shift(start, 7) if shift(start, 13) else None,
        days=days,
        totals=aggregate(
            tuple(r for d in days for r in d.reports), tuple(e for d in days for e in d.expenses)
        ),
    )
