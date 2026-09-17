import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hub.calendars.models import Calendar, CalendarAssignment
from hub.integrations.models import GpsBinding, TelegramBinding
from hub.technicians.models import Technician
from tests.test_api import calendar, create


def confirmation(person):
    return {"confirmation": "DELETE", "expected_updated_at": person["updated_at"]}


async def test_stale_delete_does_not_remove_renamed_profile(client):
    person = await create(client)
    path = f"/api/technicians/{person['id']}"
    changed = await client.patch(path, json={"first_name": "Renamed"})
    assert changed.status_code == 200
    response = await client.request("DELETE", path, json=confirmation(person))
    assert response.status_code == 409
    assert (await client.get(path)).json()["first_name"] == "Renamed"
    assert (
        await client.request("DELETE", path, json=confirmation(changed.json()))
    ).status_code == 204


@pytest.mark.parametrize("field", ["first_name", "last_name", "driver_license_id"])
@pytest.mark.parametrize("value", ["bad\x00value", "bad\nvalue", "bad\x7fvalue"])
async def test_control_characters_are_validation_errors(client, field, value):
    person = await create(client)
    result = await client.patch(f"/api/technicians/{person['id']}", json={field: value})
    assert result.status_code == 422
    assert "bad" not in result.text


async def test_blank_license_normalizes_to_null(client):
    person = await create(client)
    response = await client.patch(
        f"/api/technicians/{person['id']}", json={"driver_license_id": "   "}
    )
    assert response.status_code == 200 and response.json()["driver_license_id"] is None


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:image/svg+xml,test",
        "file:///C:/private",
        "ftp://example.invalid/a",
    ],
)
async def test_unsafe_photo_schemes_rejected(client, url):
    response = await client.post(
        "/api/technicians", json={"first_name": "Photo", "last_name": "Test", "photo_url": url}
    )
    assert response.status_code == 422


async def test_unicode_names_duplicate_people_and_timestamp_contract(client):
    first, second = await asyncio.gather(
        create(client, first_name="  Zoë  ", last_name="李"),
        create(client, first_name="Zoë", last_name="李"),
    )
    assert first["id"] != second["id"]
    assert first["first_name"] == "Zoë"
    assert datetime.fromisoformat(first["updated_at"].replace("Z", "+00:00")).tzinfo
    assert len((await client.get("/api/technicians", params={"q": "李 Zoë"})).json()) == 2


@pytest.mark.parametrize("path", ["/api/technicians/bad-id", "/api/calendars/bad-id"])
async def test_malformed_mutation_uuid_is_422(client, path):
    assert (
        await client.patch(
            path, json={"name": "Test"} if "calendars" in path else {"first_name": "Test"}
        )
    ).status_code == 422


async def test_database_enforces_nonempty_calendar_name(engine):
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(Calendar.__table__.insert().values(id=uuid4(), name="   "))


async def test_database_rejects_active_assignment_without_calendar(client, engine):
    person = await create(client)
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                CalendarAssignment.__table__.insert().values(
                    id=uuid4(),
                    technician_id=UUID(person["id"]),
                    calendar_id=None,
                    calendar_name="History",
                    is_active=True,
                )
            )


@pytest.mark.parametrize("model", [TelegramBinding, GpsBinding])
async def test_binding_foreign_key_rejects_orphan(engine, model):
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(model.__table__.insert().values(technician_id=uuid4()))


async def test_database_partial_unique_indexes_independent_of_service(client, engine):
    person = await create(client)
    one, two = await calendar(client, "One"), await calendar(client, "Two")
    async with engine.begin() as db:
        await db.execute(
            CalendarAssignment.__table__.insert().values(
                id=uuid4(),
                technician_id=UUID(person["id"]),
                calendar_id=UUID(one["id"]),
                calendar_name="One",
                is_active=True,
            )
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                CalendarAssignment.__table__.insert().values(
                    id=uuid4(),
                    technician_id=UUID(person["id"]),
                    calendar_id=UUID(two["id"]),
                    calendar_name="Two",
                    is_active=True,
                )
            )


async def test_concurrent_assignments_to_same_technician(client, engine):
    person = await create(client)
    one, two = await calendar(client, "One"), await calendar(client, "Two")
    results = await asyncio.wait_for(
        asyncio.gather(
            *(
                client.put(
                    f"/api/technicians/{person['id']}/calendar", json={"calendar_id": value["id"]}
                )
                for value in [one, two]
            )
        ),
        10,
    )
    assert [r.status_code for r in results] == [200, 200]
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(CalendarAssignment)
                .where(CalendarAssignment.is_active)
            )
            == 1
        )
        assert await db.scalar(select(func.count()).select_from(CalendarAssignment)) == 2


async def test_calendar_remove_races_assignment(client, engine):
    person = await create(client)
    local = await calendar(client)
    assignment, removal = await asyncio.wait_for(
        asyncio.gather(
            client.put(
                f"/api/technicians/{person['id']}/calendar", json={"calendar_id": local["id"]}
            ),
            client.request(
                "DELETE",
                f"/api/calendars/{local['id']}",
                json={"confirmation": "DELETE", "detach_assigned": True},
            ),
        ),
        10,
    )
    assert removal.status_code == 204
    assert assignment.status_code in {200, 404}
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(CalendarAssignment)
                .where(CalendarAssignment.is_active)
            )
            == 0
        )
        assert await db.scalar(select(func.count()).select_from(Technician)) == 1


async def test_update_delete_race_is_serialized(client):
    person = await create(client)
    path = f"/api/technicians/{person['id']}"
    changed, removed = await asyncio.wait_for(
        asyncio.gather(
            client.patch(path, json={"last_name": "Changed"}),
            client.request("DELETE", path, json=confirmation(person)),
        ),
        10,
    )
    assert (changed.status_code, removed.status_code) in {(200, 409), (404, 204)}
    if removed.status_code == 204:
        assert (await client.get(path)).status_code == 404
    else:
        assert (await client.get(path)).json()["last_name"] == "Changed"


async def test_concurrent_duplicate_binding_insert_has_one_winner(client, engine):
    person = await create(client)

    async def insert_binding():
        try:
            async with engine.begin() as db:
                await db.execute(
                    TelegramBinding.__table__.insert().values(
                        technician_id=UUID(person["id"]), telegram_user_id=9000000001
                    )
                )
            return "OK"
        except IntegrityError:
            return "CONFLICT"

    assert sorted(await asyncio.gather(insert_binding(), insert_binding())) == ["CONFLICT", "OK"]


async def test_delete_failure_rolls_back_all_dependents(client, engine):
    local = await calendar(client)
    person = await create(client, calendar_id=local["id"])
    async with engine.begin() as db:
        await db.execute(GpsBinding.__table__.insert().values(technician_id=UUID(person["id"])))
        await db.execute(
            text(
                "CREATE FUNCTION audit_fail_delete() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'simulated private failure'; END $$"
            )
        )
        await db.execute(
            text(
                "CREATE TRIGGER audit_fail BEFORE DELETE ON gps_bindings "
                "FOR EACH ROW EXECUTE FUNCTION audit_fail_delete()"
            )
        )
    try:
        response = await client.request(
            "DELETE", f"/api/technicians/{person['id']}", json=confirmation(person)
        )
        assert response.status_code == 503 and "private failure" not in response.text
        async with engine.connect() as db:
            for model in [Technician, CalendarAssignment, GpsBinding]:
                assert await db.scalar(select(func.count()).select_from(model)) == 1
    finally:
        async with engine.begin() as db:
            await db.execute(text("DROP TRIGGER audit_fail ON gps_bindings"))
            await db.execute(text("DROP FUNCTION audit_fail_delete()"))


async def test_calendar_rename_response_survives_postcommit_delete(client, engine, monkeypatch):
    local = await calendar(client)
    original = AsyncSession.commit

    async def commit_then_delete(db):
        await original(db)
        async with engine.begin() as connection:
            await connection.execute(
                Calendar.__table__.delete().where(Calendar.id == UUID(local["id"]))
            )

    monkeypatch.setattr(AsyncSession, "commit", commit_then_delete)
    response = await client.patch(f"/api/calendars/{local['id']}", json={"name": "Renamed"})
    assert response.status_code == 200 and response.json()["name"] == "Renamed"


async def test_error_responses_hide_sql_and_sensitive_inputs(client):
    await calendar(client, "Duplicate")
    response = await client.post("/api/calendars", json={"name": "Duplicate"})
    assert response.status_code == 409
    assert all(
        word not in response.text for word in ["INSERT", "asyncpg", "Traceback", "parameters"]
    )


@pytest.mark.parametrize("version", [None, "2026-01-01T00:00:00"])
async def test_delete_requires_timezone_aware_record_version(client, version):
    person = await create(client)
    payload = {"confirmation": "DELETE"}
    if version is not None:
        payload["expected_updated_at"] = version
    assert (
        await client.request("DELETE", f"/api/technicians/{person['id']}", json=payload)
    ).status_code == 422
    assert (await client.get(f"/api/technicians/{person['id']}")).status_code == 200


@pytest.mark.parametrize("endpoint", ["/api/health", "/api/technicians"])
async def test_real_database_connection_failure_has_safe_response(endpoint):
    from httpx import ASGITransport, AsyncClient

    from hub.core.config import Settings
    from hub.main import create_app

    app = create_app(
        Settings(
            database_url="postgresql+asyncpg://hub:never_logged@127.0.0.1:1/technician_hub_test",
            app_env="test",
        )
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://audit.local",
        ) as http:
            http.cookies.set("hub_session", "audit-placeholder-session")
            response = await http.get(endpoint)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "unavailable"
            assert "never_logged" not in response.text


async def test_raw_calendar_delete_cannot_leave_active_orphan(client, engine):
    local = await calendar(client)
    await create(client, calendar_id=local["id"])
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(Calendar.__table__.delete().where(Calendar.id == UUID(local["id"])))


async def test_assignment_racing_technician_delete_leaves_no_orphans(client, engine):
    local = await calendar(client)
    person = await create(client)
    path = f"/api/technicians/{person['id']}"
    assignment, removal = await asyncio.wait_for(
        asyncio.gather(
            client.put(path + "/calendar", json={"calendar_id": local["id"]}),
            client.request("DELETE", path, json=confirmation(person)),
        ),
        10,
    )
    assert assignment.status_code in {200, 404} and removal.status_code == 204
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(CalendarAssignment)) == 0


async def test_search_control_character_is_validation_error(client):
    response = await client.get("/api/technicians", params={"q": "bad\x00query"})
    assert response.status_code == 422
    assert "bad" not in response.text


async def test_version_guard_preserves_stage1_delete_audit(client, engine, credentials):
    from hub.audit.models import AuditEvent

    person = await create(client)
    path = f"/api/technicians/{person['id']}"
    updated = (await client.patch(path, json={"first_name": "Changed"})).json()
    assert (await client.request("DELETE", path, json=confirmation(person))).status_code == 409
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "technician.deleted")
            )
            == 0
        )
    assert (await client.request("DELETE", path, json=confirmation(updated))).status_code == 204
    async with engine.connect() as db:
        row = (
            await db.execute(
                select(AuditEvent.actor_id, AuditEvent.target_id, AuditEvent.outcome).where(
                    AuditEvent.action == "technician.deleted"
                )
            )
        ).one()
        assert row == (credentials["id"], UUID(person["id"]), "SUCCESS")
        assert await db.scalar(select(func.count()).select_from(Technician)) == 0
