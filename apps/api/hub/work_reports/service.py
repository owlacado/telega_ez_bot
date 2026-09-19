"""Short transactions; technician lock precedes binding/session locks everywhere."""

import hashlib
import json
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import lazyload

from hub.audit.service import audit
from hub.calendar_events.service import read_schedule
from hub.calendars.models import CalendarAssignment
from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.telegram.common import can_deliver
from hub.work_reports.models import TechnicianFormSession, WorkReport, WorkReportRevision
from hub.work_reports.schemas import FormRead, JobRead, ReportRead, SubmissionRead


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical_job(job):
    """Derive occurrence identity from server facts, including older cached forms."""
    occurrence = [job["provider_event_id"]]
    if job.get("recurring_event_id") and job.get("original_start_time"):
        original = datetime.fromisoformat(job["original_start_time"])
        if original.tzinfo is None:
            unavailable()
        occurrence = [job["recurring_event_id"], original.astimezone(UTC).isoformat()]
    return {**job, "occurrence_key": digest(json.dumps([str(job["calendar_id"]), occurrence]))}


def unavailable():
    raise HTTPException(
        410, "This form is unavailable. Open Submit Report again in your private bot."
    )


async def database_now(db):
    # Wall clock AFTER lock acquisition, not transaction-start now(), and not
    # a potentially skewed API/worker process clock.
    return await db.scalar(select(func.clock_timestamp()))


async def issue(db, event, bot_id, settings):
    if not (
        event.kind == "COMMAND"
        and event.chat_type == "private"
        and event.user_id
        and event.user_id == event.chat_id
        and not event.user_is_bot
        and not event.anonymous
    ):
        return None
    identifier = await db.scalar(
        select(TelegramBinding.technician_id).where(
            TelegramBinding.telegram_user_id == event.user_id, TelegramBinding.bot_id == bot_id
        )
    )
    if not identifier:
        return None
    tech = await db.scalar(
        select(Technician)
        .options(lazyload("*"))
        .where(Technician.id == identifier)
        .with_for_update()
    )
    binding = await db.get(
        TelegramBinding, identifier, populate_existing=True, with_for_update=True
    )
    if (
        not tech
        or tech.status != "ACTIVE"
        or not binding
        or binding.telegram_user_id != event.user_id
        or not can_deliver(binding, "PRIVATE_TELEGRAM", bot_id)
    ):
        return None
    # Bound active credentials, allowing two legitimate forms to race safely.
    sessions = await db.scalars(
        select(TechnicianFormSession)
        .where(
            TechnicianFormSession.technician_id == identifier,
            TechnicianFormSession.status == "OPEN",
        )
        .order_by(TechnicianFormSession.created_at.desc())
        .with_for_update()
    )
    current_time = await database_now(db)
    for index, previous in enumerate(sessions):
        if previous.expires_at <= current_time or index >= 4:
            previous.status = "EXPIRED" if previous.expires_at <= current_time else "REVOKED"
            previous.choices = None
            previous.selected = None
    token = secrets.token_urlsafe(32)
    value = TechnicianFormSession(
        id=uuid4(),
        technician_id=identifier,
        token_hash=digest(token),
        telegram_user_id=event.user_id,
        bot_id=bot_id,
        binding_generation=binding.private_generation,
        created_at=current_time,
        expires_at=current_time + timedelta(seconds=settings.work_report_session_seconds),
    )
    db.add(value)
    audit(db, "work_report.session_issued", value.id, actor_kind="TECHNICIAN")
    return token


async def authorize(db, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        unavailable()
    identifier = await db.scalar(
        select(TechnicianFormSession.technician_id).where(
            TechnicianFormSession.token_hash == digest(token)
        )
    )
    if identifier is None:
        unavailable()
    tech = await db.scalar(
        select(Technician)
        .options(lazyload("*"))
        .where(Technician.id == identifier)
        .with_for_update()
    )
    binding = await db.get(
        TelegramBinding, identifier, with_for_update=True, populate_existing=True
    )
    value = await db.scalar(
        select(TechnicianFormSession)
        .where(TechnicianFormSession.token_hash == digest(token))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not tech or tech.status != "ACTIVE" or not binding or not value:
        unavailable()
    if (
        value.purpose != "WORK_REPORT"
        or value.status in {"REVOKED", "EXPIRED"}
        or binding.telegram_user_id != value.telegram_user_id
        or binding.private_generation != value.binding_generation
        or not can_deliver(binding, "PRIVATE_TELEGRAM", value.bot_id)
    ):
        unavailable()
    # A committed receipt can be replayed after TTL; open submissions cannot.
    if value.status != "SUBMITTED" and value.expires_at <= await database_now(db):
        unavailable()
    return value, tech


def public_job(job, submitted=False):
    return JobRead(
        **{
            key: job[key]
            for key in (
                "choice_id",
                "operational_date",
                "start_time",
                "end_time",
                "sequence",
                "title",
                "location",
            )
        },
        submitted=submitted,
    )


async def form_view(db, value):
    if value.status == "SUBMITTED":
        return FormRead(status="SUBMITTED", expires_at=value.expires_at, report_id=value.report_id)
    choices = [canonical_job(job) for job in value.choices or []]
    existing = set(
        (
            await db.scalars(
                select(WorkReport.occurrence_key).where(
                    WorkReport.technician_id == value.technician_id,
                    WorkReport.occurrence_key.in_([job["occurrence_key"] for job in choices]),
                )
            )
        ).all()
    )
    return FormRead(
        status="OPEN",
        expires_at=value.expires_at,
        jobs=[public_job(job, job["occurrence_key"] in existing) for job in choices],
        selected=public_job(value.selected) if value.selected else None,
    )


async def open_form(request, token):
    factory = request.app.state.session_factory
    async with factory() as db, db.begin():
        value, _ = await authorize(db, token)
        if value.status == "SUBMITTED" or value.choices is not None:
            return await form_view(db, value)
        technician_id = value.technician_id
    # Reuse canonical Stage 3 read, including complete filtering and change checks.
    request.state.manager_id = None
    schedule = await read_schedule(request, technician_id, worker=True)
    if schedule.state != "READY":
        raise HTTPException(
            409, "Jobs are temporarily unavailable. Check your calendar connection and try again."
        )
    choices = []
    for sequence, job in enumerate(schedule.jobs, 1):
        occurrence = (
            [job.recurring_event_id, job.original_start_time.isoformat()]
            if job.recurring_event_id and job.original_start_time
            else [job.provider_event_id]
        )
        choices.append(
            canonical_job(
                dict(
                    choice_id=str(uuid4()),
                    calendar_id=str(job.calendar_id),
                    occurrence_key=digest(json.dumps([str(job.calendar_id), occurrence])),
                    provider_event_id=job.provider_event_id,
                    recurring_event_id=job.recurring_event_id,
                    original_start_time=job.original_start_time.isoformat()
                    if job.original_start_time
                    else None,
                    operational_date=job.display_date.isoformat(),
                    start_time=job.display_start_time,
                    end_time=job.display_end_time,
                    sequence=job.job_number or sequence,
                    title=job.schedule_summary[:500],
                    location=(job.location or "")[:1000],
                )
            )
        )
    async with factory() as db, db.begin():
        value, _ = await authorize(db, token)
        if value.status == "OPEN" and value.choices is None:
            value.choices = choices
        return await form_view(db, value)


async def select_job(factory, token, choice_id):
    async with factory() as db, db.begin():
        value, _ = await authorize(db, token)
        if value.status != "OPEN":
            raise HTTPException(409, "FORM_ALREADY_SUBMITTED")
        selected = next(
            (job for job in value.choices or [] if job["choice_id"] == str(choice_id)), None
        )
        if not selected:
            unavailable()
        selected = canonical_job(selected)
        if value.selected:
            value.selected = canonical_job(value.selected)
        if value.selected and value.selected != selected:
            raise HTTPException(409, "Job is already selected. Open a new form to change jobs.")
        if value.selected is None:
            calendar_id = await db.scalar(
                select(CalendarAssignment.calendar_id).where(
                    CalendarAssignment.technician_id == value.technician_id,
                    CalendarAssignment.is_active.is_(True),
                )
            )
            if str(calendar_id) != selected["calendar_id"]:
                raise HTTPException(409, "Calendar changed before selection. Open a new form.")
        exists = await db.scalar(
            select(WorkReport.id).where(
                WorkReport.technician_id == value.technician_id,
                WorkReport.calendar_id == UUID(selected["calendar_id"]),
                WorkReport.occurrence_key == selected["occurrence_key"],
            )
        )
        if exists:
            raise HTTPException(409, "This job already has a submitted report.")
        value.selected = selected
        return await form_view(db, value)


async def submit(factory, token, payload):
    fingerprint = digest(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    )
    async with factory() as db, db.begin():
        value, tech = await authorize(db, token)
        if value.status == "SUBMITTED":
            if value.payload_hash != fingerprint:
                raise HTTPException(409, "FORM_ALREADY_SUBMITTED")
            return SubmissionRead(report_id=value.report_id)
        job = value.selected
        if not job:
            raise HTTPException(409, "Select a scheduled job first.")
        job = canonical_job(job)
        exists = await db.scalar(
            select(WorkReport.id).where(
                WorkReport.technician_id == tech.id,
                WorkReport.calendar_id == UUID(job["calendar_id"]),
                WorkReport.occurrence_key == job["occurrence_key"],
            )
        )
        if exists:
            raise HTTPException(409, "This job already has a submitted report.")
        report = WorkReport(
            id=uuid4(),
            technician_id=tech.id,
            calendar_id=UUID(job["calendar_id"]),
            occurrence_key=job["occurrence_key"],
        )
        db.add(report)
        await db.flush()
        fields = payload.model_dump(exclude={"reviews"})
        revision = WorkReportRevision(
            report_id=report.id,
            revision_number=1,
            technician_name=f"{tech.first_name} {tech.last_name}"[:250],
            operational_date=date.fromisoformat(job["operational_date"]),
            **{
                key: job[key]
                for key in (
                    "start_time",
                    "end_time",
                    "sequence",
                    "title",
                    "location",
                    "provider_event_id",
                    "recurring_event_id",
                    "original_start_time",
                )
            },
            **fields,
            google_reviews=payload.reviews.GOOGLE,
            groupon_reviews=payload.reviews.GROUPON,
            facebook_reviews=payload.reviews.FACEBOOK,
        )
        db.add(revision)
        value.status, value.report_id, value.payload_hash, value.submitted_at = (
            "SUBMITTED",
            report.id,
            fingerprint,
            await database_now(db),
        )
        value.choices, value.selected = None, None
        audit(db, "work_report.submitted", report.id, actor_kind="TECHNICIAN")
        await db.flush()
        response = SubmissionRead(report_id=report.id)
    # Form receipt is authoritative. No provider call can roll back this commit.
    return response


def report_view(report, revision):
    fields = {
        key: getattr(revision, key)
        for key in (
            "technician_name",
            "operational_date",
            "start_time",
            "end_time",
            "sequence",
            "title",
            "location",
            "revision_number",
            "submitted_at",
            "amount_closed",
            "payment_method",
            "closed_by",
            "comments",
            "yearly_maintenance_plan_provided",
        )
    }
    return ReportRead(
        id=report.id,
        technician_id=report.technician_id,
        **fields,
        reviews=dict(
            GOOGLE=revision.google_reviews,
            GROUPON=revision.groupon_reviews,
            FACEBOOK=revision.facebook_reviews,
        ),
    )


def current_reports():
    return select(WorkReport, WorkReportRevision).join(
        WorkReportRevision,
        (WorkReportRevision.report_id == WorkReport.id)
        & (WorkReportRevision.revision_number == WorkReport.current_revision_number),
    )
