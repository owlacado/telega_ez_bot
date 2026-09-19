"""Synthetic accounting records only; callers must use the guarded test database."""

import hashlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from hub.calendars.models import Calendar
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.technicians.models import Technician
from hub.work_reports.models import WorkReport, WorkReportRevision

GOLDEN = json.loads((Path(__file__).parent / "fixtures/accounting_legacy_week.json").read_text())


async def seed(factory, start, *, technician_id=None, reports=None, expenses=None):
    async with factory() as db, db.begin():
        assert db.bind.url.database == "technician_hub_test"
        if technician_id is None:
            tech = Technician(
                id=uuid4(),
                first_name="Accounting",
                last_name="Synthetic",
                accounting_timezone="America/Los_Angeles",
            )
            db.add(tech)
            technician_id = tech.id
        calendar = Calendar(id=uuid4(), name=f"Synthetic accounting {uuid4()}")
        db.add(calendar)
        await db.flush()
        for i, r in enumerate(GOLDEN["reports"] if reports is None else reports):
            identifier = uuid4()
            parent = WorkReport(
                id=identifier,
                technician_id=technician_id,
                calendar_id=calendar.id,
                occurrence_key=hashlib.sha256(identifier.bytes).hexdigest(),
                current_revision_number=r.get("revision_number", 1),
            )
            db.add(parent)
            await db.flush()
            for rev in range(1, parent.current_revision_number + 1):
                day = start + timedelta(days=r["day"])
                db.add(
                    WorkReportRevision(
                        report_id=identifier,
                        revision_number=rev,
                        technician_name="Accounting Synthetic",
                        operational_date=day,
                        start_time="09:00",
                        end_time="10:00",
                        sequence=i + 1,
                        title="Synthetic job",
                        location="Synthetic location",
                        provider_event_id=str(identifier),
                        amount_closed=Decimal(
                            r.get("previous_amount")
                            if rev < parent.current_revision_number
                            else r["amount"]
                        ),
                        payment_method=r["payment_method"],
                        closed_by=r.get("closed_by", "MYSELF"),
                        comments="<script>synthetic report</script>",
                        yearly_maintenance_plan_provided=r.get("maintenance", False),
                        google_reviews=r.get("google", 0)
                        if rev == parent.current_revision_number
                        else 99,
                        groupon_reviews=r.get("groupon", 0),
                        facebook_reviews=r.get("facebook", 0),
                        submitted_at=datetime.combine(
                            day + timedelta(days=1), time(1), tzinfo=ZoneInfo("America/Los_Angeles")
                        ),
                    )
                )
        for e in GOLDEN["expenses"] if expenses is None else expenses:
            identifier = uuid4()
            number = e.get("revision_number", 1)
            db.add(
                TechnicianExpense(
                    id=identifier, technician_id=technician_id, current_revision_number=number
                )
            )
            await db.flush()
            day = start + timedelta(days=e["day"])
            for rev in range(1, number + 1):
                db.add(
                    ExpenseRevision(
                        expense_id=identifier,
                        revision_number=rev,
                        technician_name="Accounting Synthetic",
                        expense_date=day,
                        accounting_timezone="America/Los_Angeles",
                        expense_type=e.get("expense_type", "Synthetic supplies"),
                        amount=Decimal(e.get("previous_amount") if rev < number else e["amount"]),
                        note="<script>synthetic expense</script>",
                        submitted_at=datetime.combine(
                            day, time(12), tzinfo=ZoneInfo("America/Los_Angeles")
                        ),
                    )
                )
    return technician_id
