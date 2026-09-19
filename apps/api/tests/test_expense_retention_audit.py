"""Business-record retention combinations using fake report and expense flows."""

import pytest
from sqlalchemy import select

from hub.audit.models import AuditEvent
from hub.expenses.models import TechnicianExpense
from tests.test_expenses import issue, send
from tests.test_work_reports import BASE, PAYLOAD, ready, selected
from tests.test_work_reports import assigned as assigned
from tests.test_work_reports import google as google

report_ready = ready


@pytest.mark.parametrize(
    "report,expense", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_retention_combinations(app, client, report_ready, report, expense):
    tid = report_ready
    await client.patch(f"/api/technicians/{tid}", json={"accounting_timezone": "America/Denver"})
    if report:
        _, headers, _ = await selected(app, client)
        assert (
            await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
        ).status_code == 200
    if expense:
        result = await send(app, await issue(app))
        async with app.state.session_factory() as db:
            audit = await db.scalar(
                select(AuditEvent).where(AuditEvent.action == "expense.submitted")
            )
            assert audit.actor_kind == "TECHNICIAN" and audit.actor_id is None
            assert audit.target_id == result.expense_id
            row = await db.get(TechnicianExpense, audit.target_id)
            assert row.technician_id == tid
    profile = (await client.get(f"/api/technicians/{tid}")).json()
    response = await client.request(
        "DELETE",
        f"/api/technicians/{tid}",
        json={"confirmation": "DELETE", "expected_updated_at": profile["updated_at"]},
    )
    assert response.status_code == (409 if report or expense else 204)
