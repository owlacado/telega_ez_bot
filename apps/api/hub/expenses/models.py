import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from hub.core.database import Base


class TechnicianExpense(Base):
    __tablename__ = "technician_expenses"
    __table_args__ = (
        CheckConstraint("current_revision_number > 0", name="current_revision"),
        ForeignKeyConstraint(
            ["id", "current_revision_number"],
            ["expense_revisions.expense_id", "expense_revisions.revision_number"],
            name="fk_expense_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="RESTRICT"), index=True
    )
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExpenseRevision(Base):
    __tablename__ = "expense_revisions"
    __table_args__ = (
        UniqueConstraint("expense_id", "revision_number", name="uq_expense_revision"),
        CheckConstraint("revision_number > 0", name="positive_revision"),
        CheckConstraint("amount >= 0 AND amount <= 9999999999.99", name="money"),
        CheckConstraint("scale(amount) <= 2", name="money_scale"),
        CheckConstraint(
            "length(trim(expense_type)) BETWEEN 1 AND 100 AND expense_type !~ '[<>[:cntrl:]]'",
            name="type",
        ),
        CheckConstraint("length(note) <= 4000", name="note"),
        CheckConstraint(
            "expense_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'", name="date"
        ),
        CheckConstraint("length(technician_name) > 0", name="name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technician_expenses.id", ondelete="RESTRICT")
    )
    revision_number: Mapped[int] = mapped_column(Integer, default=1)
    technician_name: Mapped[str] = mapped_column(String(250))
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    accounting_timezone: Mapped[str] = mapped_column(String(64))
    expense_type: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric())
    note: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
