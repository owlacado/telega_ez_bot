"""Business activity intents on the existing Telegram outbox; no provider I/O."""

from sqlalchemy import select

from hub.auth.security import now
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.integrations.models import TelegramBinding
from hub.telegram.common import can_deliver
from hub.telegram.models import TelegramOutbox
from hub.work_reports.models import WorkReport, WorkReportRevision

ACTIVITY_KINDS = {"WORK_REPORT", "EXPENSE"}


async def enqueue_activity(db, technician_id, bot_id, *, report_id=None, expense_id=None):
    binding = await db.get(TelegramBinding, technician_id)
    available = binding is not None and can_deliver(binding, "WORK_GROUP", bot_id)
    # A missing/unavailable group must never roll back a financial submission or
    # become an instruction to publish historical facts to a later replacement.
    db.add(
        TelegramOutbox(
            technician_id=technician_id,
            bot_id=bot_id,
            destination="WORK_GROUP",
            kind="WORK_REPORT" if report_id else "EXPENSE",
            report_id=report_id,
            expense_id=expense_id,
            generation=binding.group_generation if binding else 0,
            private_generation=binding.private_generation if binding else 0,
            activity_chat_id=binding.telegram_group_chat_id if binding else None,
            activity_user_id=binding.telegram_user_id if binding else None,
            state="QUEUED" if available else "CANCELLED",
            error_code=None if available else "DESTINATION_UNAVAILABLE",
            finished_at=None if available else now(),
        )
    )


def bound(job, binding):
    return (
        binding is not None
        and job.activity_chat_id == binding.telegram_group_chat_id
        and job.activity_user_id == binding.telegram_user_id
        and job.generation == binding.group_generation
        and job.private_generation == binding.private_generation
        and can_deliver(binding, "WORK_GROUP", job.bot_id)
    )


def clip(value, limit):
    # Plain text transport (no parse_mode); bound UTF-16 length including emoji.
    raw = str(value or "").encode("utf-16-le")
    if len(raw) <= limit * 2:
        return str(value or "")
    return raw[: (limit - 1) * 2].decode("utf-16-le", errors="ignore") + "\u2026"


async def render_activity(db, job):
    if job.kind == "WORK_REPORT":
        row = (
            await db.execute(
                select(WorkReportRevision)
                .join(WorkReport, WorkReport.id == WorkReportRevision.report_id)
                .where(
                    WorkReport.id == job.report_id,
                    WorkReport.technician_id == job.technician_id,
                    WorkReportRevision.revision_number == 1,
                )
            )
        ).scalar_one()
        message = (
            f"Work report saved - {clip(row.technician_name, 250)}\n"
            f"{row.operational_date} - {row.start_time}-{row.end_time}\n"
            f"Job {row.sequence}: {clip(row.title, 500)}\n"
            f"Location: {clip(row.location, 500)}\n"
            f"Amount: ${row.amount_closed:.2f} - {row.payment_method.replace('_', ' ').title()}\n"
            f"Closed by: {'Myself' if row.closed_by == 'MYSELF' else 'Call center'}\n"
            f"Reviews: Google {row.google_reviews}, Groupon {row.groupon_reviews}, "
            f"Facebook {row.facebook_reviews}\n"
            f"Maintenance plan: {'Yes' if row.yearly_maintenance_plan_provided else 'No'}\n"
            f"Comments: {clip(row.comments, 1000) or 'None'}"
        )
    else:
        row = (
            await db.execute(
                select(ExpenseRevision)
                .join(TechnicianExpense, TechnicianExpense.id == ExpenseRevision.expense_id)
                .where(
                    TechnicianExpense.id == job.expense_id,
                    TechnicianExpense.technician_id == job.technician_id,
                    ExpenseRevision.revision_number == 1,
                )
            )
        ).scalar_one()
        message = (
            f"Expense saved - {clip(row.technician_name, 250)}\n"
            f"Date: {row.expense_date} ({row.accounting_timezone})\n"
            f"Type: {clip(row.expense_type, 100)}\nAmount: ${row.amount:.2f}\n"
            f"Note: {clip(row.note, 1800) or 'None'}"
        )
    return clip(message, 3900)
