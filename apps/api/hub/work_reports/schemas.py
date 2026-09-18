import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Payment = Literal["CASH", "ZELLE", "CHECK", "CREDIT_CARD", "VENMO", "SUPER", "ESTIMATE", "CANCEL"]


def forces_zero_amount(payment: str) -> bool:
    return payment in {"ESTIMATE", "CANCEL"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Reviews(StrictModel):
    GOOGLE: int = Field(ge=0, le=100, strict=True)
    GROUPON: int = Field(ge=0, le=100, strict=True)
    FACEBOOK: int = Field(ge=0, le=100, strict=True)


class ReportInput(StrictModel):
    amount_closed: Decimal = Field(
        ge=0, le=Decimal("9999999999.99"), max_digits=12, decimal_places=2
    )
    payment_method: Payment
    closed_by: Literal["MYSELF", "CALL_CENTER"]
    comments: str = Field(default="", max_length=4000)
    yearly_maintenance_plan_provided: bool = Field(strict=True)
    reviews: Reviews

    @field_validator("amount_closed", mode="before", json_schema_input_type=str)
    @classmethod
    def money(cls, value):
        if not isinstance(value, (str, Decimal)) or not re.fullmatch(
            r"[0-9]{1,10}(?:\.[0-9]{1,2})?", str(value)
        ):
            raise ValueError("Use a nonnegative currency string with at most two decimal places.")
        return Decimal(value).quantize(Decimal("0.01"))

    @field_validator("payment_method", mode="before")
    @classmethod
    def payment(cls, value):
        if isinstance(value, str):
            value = value.strip().upper().replace(" ", "_")
            return "CREDIT_CARD" if value in {"CASH_APP", "CREDIT_CARD_/_CASH_APP"} else value
        return value

    @field_validator("comments")
    @classmethod
    def text(cls, value):
        return "".join(
            c for c in value if not unicodedata.category(c).startswith("C") or c in "\n\t"
        ).strip()

    @model_validator(mode="after")
    def zero(self):
        if forces_zero_amount(self.payment_method):
            self.amount_closed = Decimal("0.00")
        return self


class JobRead(StrictModel):
    choice_id: UUID
    operational_date: date
    start_time: str
    end_time: str
    sequence: int
    title: str
    location: str
    submitted: bool = False


class SelectJob(StrictModel):
    choice_id: UUID


class FormRead(StrictModel):
    status: Literal["OPEN", "SUBMITTED"]
    expires_at: datetime
    jobs: list[JobRead] = Field(default_factory=list)
    selected: JobRead | None = None
    report_id: UUID | None = None
    payment_choices: list[Payment] = [
        "CASH",
        "ZELLE",
        "CHECK",
        "CREDIT_CARD",
        "VENMO",
        "SUPER",
        "ESTIMATE",
        "CANCEL",
    ]
    zero_amount_choices: list[Payment] = Field(
        default_factory=lambda: [value for value in get_args(Payment) if forces_zero_amount(value)]
    )


class SubmissionRead(StrictModel):
    report_id: UUID
    revision_number: int = 1
    message: str = "Report submitted successfully."


class ReportRead(ReportInput):
    id: UUID
    technician_id: UUID
    technician_name: str
    operational_date: date
    start_time: str
    end_time: str
    sequence: int
    title: str
    location: str
    revision_number: int
    submitted_at: datetime


class ReportList(StrictModel):
    reports: list[ReportRead]
    limit: int
