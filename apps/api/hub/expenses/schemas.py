import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from hub.work_reports.schemas import StrictModel


class ExpenseInput(StrictModel):
    expense_type: str = Field(max_length=100)
    amount: Decimal = Field(ge=0, le=Decimal("9999999999.99"), max_digits=12, decimal_places=2)
    note: str = Field(default="", max_length=4000)

    @field_validator("amount", mode="before", json_schema_input_type=str)
    @classmethod
    def money(cls, value):
        if not isinstance(value, (str, Decimal)) or not re.fullmatch(
            r"[0-9]{1,10}(?:\.[0-9]{1,2})?", str(value)
        ):
            raise ValueError("Use a nonnegative currency string with at most two decimal places.")
        return Decimal(value).quantize(Decimal("0.01"))

    @field_validator("expense_type")
    @classmethod
    def kind(cls, value):
        value = value.strip()
        if not value or any(c in "<>" or unicodedata.category(c).startswith("C") for c in value):
            raise ValueError("Enter a plain text expense type without markup or controls.")
        return value

    @field_validator("note")
    @classmethod
    def text(cls, value):
        return "".join(
            c for c in value if not unicodedata.category(c).startswith("C") or c in "\n\t"
        ).strip()


class ExpenseReceipt(StrictModel):
    expense_id: UUID
    revision_number: int = 1
    message: str = "Expense saved successfully."


class ExpenseForm(StrictModel):
    status: Literal["OPEN", "SUBMITTED"]
    expires_at: datetime
    technician_name: str
    accounting_timezone: str | None
    expense_date: date | None
    expense_id: UUID | None = None


class ExpenseRead(ExpenseInput):
    id: UUID
    technician_id: UUID
    technician_name: str
    expense_date: date
    accounting_timezone: str
    revision_number: int
    submitted_at: datetime


class ExpenseList(StrictModel):
    expenses: list[ExpenseRead]
    limit: int
    today: date | None
    accounting_timezone: str | None
    today_total: Decimal
    today_count: int
