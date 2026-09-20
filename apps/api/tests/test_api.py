from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from hub.calendars.models import CalendarAssignment
from hub.integrations.models import GpsBinding, TelegramBinding
from hub.technicians.models import Technician


async def create(client: AsyncClient, **overrides) -> dict:
    response = await client.post(
        "/api/technicians", json={"first_name": "Demo", "last_name": "Technician", **overrides}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def calendar(client: AsyncClient, name: str = "DEMO - Calendar") -> dict:
    response = await client.post("/api/calendars", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def test_health(client):
    response = await client.get("/api/health")
    assert response.json() == {
        "status": "ok",
        "database": "connected",
        "version": "0.3.0",
        "release_commit": "development",
    }
    assert response.headers["cache-control"] == "no-store"


async def test_create_list_get_update(client, engine):
    person = await create(client, first_name="  Demo  ")
    identifier = UUID(person["id"])
    assert person["first_name"] == "Demo"
    assert person["calendar"] is None
    assert person["integrations"]["telegram_private"] == "NOT_CONNECTED"
    response = await client.get("/api/technicians")
    assert len(response.json()) == 1
    assert "ssn_last4" not in response.json()[0]
    assert "driver_license_id" not in response.json()[0]
    assert (await client.get(f"/api/technicians/{identifier}")).json() == person
    updated = await client.patch(
        f"/api/technicians/{identifier}",
        json={
            "expected_record_version": person["record_version"],
            "first_name": "Updated",
            "status": "INACTIVE",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == str(identifier)
    assert "ssn_last4" not in updated.json()
    assert "driver_license_id" not in updated.json()
    assert "photo_url" not in updated.json()
    assert updated.json()["record_version"] == person["record_version"] + 1
    assert updated.json()["updated_at"] >= person["updated_at"]
    assert (await client.get("/api/technicians?q=updated%20tech")).json()[0]["id"] == str(
        identifier
    )
    assert (await client.get("/api/technicians?q=%25")).json() == []
    rejected = await client.patch(
        f"/api/technicians/{identifier}",
        json={
            "expected_record_version": updated.json()["record_version"],
            "ssn_last4": "0123",
            "driver_license_id": "DEMO-ONLY",
        },
    )
    assert rejected.status_code == 422
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(Technician)) == 1
        assert await db.scalar(select(func.count()).select_from(TelegramBinding)) == 0
        assert await db.scalar(select(func.count()).select_from(GpsBinding)) == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"first_name": "", "last_name": "Demo"},
        {"first_name": "  ", "last_name": "Demo"},
        {"first_name": "Demo", "last_name": "X" * 101},
        {"first_name": "Demo", "last_name": "Demo", "photo_url": "javascript:alert(1)"},
        {"first_name": "Demo", "last_name": "Demo", "ssn": "111223333"},
    ],
)
async def test_create_validation(client, payload):
    response = await client.post("/api/technicians", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "111223333" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"ssn_last4": "123"},
        {"ssn_last4": "12345"},
        {"ssn_last4": "abcd"},
        {"ssn_last4": "１２３４"},
        {"first_name": None},
        {"last_name": " "},
        {"status": "PARKED"},
        {"status": None},
        {"id": str(uuid4())},
        {"ssn": "111223333"},
    ],
)
async def test_patch_validation(client, payload):
    person = await create(client)
    response = await client.patch(f"/api/technicians/{person['id']}", json=payload)
    assert response.status_code == 422
    assert "111223333" not in response.text


async def test_not_found_and_bad_uuid(client):
    assert (await client.get(f"/api/technicians/{uuid4()}")).status_code == 404
    assert (await client.get("/api/technicians/not-a-uuid")).status_code == 422


async def test_calendar_assignment_change_unassign_history(client, engine):
    person = await create(client)
    first, second = await calendar(client, "DEMO - A"), await calendar(client, "DEMO - B")
    path = f"/api/technicians/{person['id']}/calendar"
    assigned = await client.put(path, json={"calendar_id": first["id"]})
    assert assigned.status_code == 200
    assert (await client.put(path, json={"calendar_id": first["id"]})).json()[
        "id"
    ] == assigned.json()["id"]
    assert (await client.get(f"/api/technicians/{person['id']}")).json()["calendar"][
        "name"
    ] == "DEMO - A"
    assert (await client.put(path, json={"calendar_id": second["id"]})).status_code == 200
    history = (await client.get(f"/api/technicians/{person['id']}/calendar-assignments")).json()
    assert len(history) == 2
    assert sum(row["is_active"] for row in history) == 1
    assert (await client.delete(path)).status_code == 204
    assert (await client.get(f"/api/technicians/{person['id']}")).json()["calendar"] is None
    assert (await client.delete(path)).status_code == 204
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(CalendarAssignment)
                .where(CalendarAssignment.is_active.is_(True))
            )
            == 0
        )
        assert await db.scalar(select(func.count()).select_from(Technician)) == 1


async def test_create_with_calendar_is_atomic(client, engine):
    response = await client.post(
        "/api/technicians",
        json={"first_name": "Demo", "last_name": "Atomic", "calendar_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert (await client.get("/api/technicians")).json() == []
    local = await calendar(client)
    person = await create(client, calendar_id=local["id"])
    assert person["calendar"]["id"] == local["id"]
    response = await client.post(
        "/api/technicians",
        json={"first_name": "Demo", "last_name": "Conflict", "calendar_id": local["id"]},
    )
    assert response.status_code == 409
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(Technician)) == 1


async def test_calendar_conflict_preserves_old_assignment(client):
    first, second = await calendar(client, "DEMO - A"), await calendar(client, "DEMO - B")
    a, b = (
        await create(client, calendar_id=first["id"]),
        await create(client, calendar_id=second["id"]),
    )
    response = await client.put(
        f"/api/technicians/{b['id']}/calendar", json={"calendar_id": first["id"]}
    )
    assert response.status_code == 409
    assert (await client.get(f"/api/technicians/{b['id']}")).json()["calendar"]["id"] == second[
        "id"
    ]
    assert a["calendar"]["id"] == first["id"]


@pytest.mark.parametrize("body", [None, {}, {"confirmation": "delete"}, {"confirmation": ""}])
async def test_delete_confirmation_required(client, body):
    person = await create(client)
    if body is not None:
        body = {**body, "expected_record_version": person["record_version"]}
    response = await client.request(
        "DELETE", f"/api/technicians/{person['id']}", **({"json": body} if body is not None else {})
    )
    assert response.status_code == 422
    assert (await client.get(f"/api/technicians/{person['id']}")).status_code == 200


async def test_permanent_delete_is_disabled_and_preserves_relationships(client, engine):
    local = await calendar(client)
    person = await create(client, calendar_id=local["id"])
    identifier = UUID(person["id"])
    async with engine.begin() as db:
        await db.execute(TelegramBinding.__table__.insert().values(technician_id=identifier))
        await db.execute(GpsBinding.__table__.insert().values(technician_id=identifier))
    response = await client.request(
        "DELETE",
        f"/api/technicians/{identifier}",
        json={
            "confirmation": "DELETE",
            "expected_record_version": (await client.get(f"/api/technicians/{identifier}")).json()[
                "record_version"
            ],
        },
    )
    assert response.status_code == 409
    assert (await client.get(f"/api/technicians/{identifier}")).status_code == 200
    assert (await client.get("/api/calendars")).json()[0]["assigned_technician"] is not None
    async with engine.connect() as db:
        for model in [Technician, CalendarAssignment, TelegramBinding, GpsBinding]:
            assert await db.scalar(select(func.count()).select_from(model)) == 1


async def test_calendar_crud_and_assigned_removal_confirmation(client):
    local = await calendar(client)
    person = await create(client, calendar_id=local["id"])
    path = f"/api/calendars/{local['id']}"
    assert (await client.post("/api/calendars", json={"name": local["name"]})).status_code == 409
    renamed = await client.patch(path, json={"name": "DEMO - Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["assigned_technician"]["id"] == person["id"]
    assert (await client.get(f"/api/technicians/{person['id']}")).json()["calendar"][
        "name"
    ] == "DEMO - Renamed"
    assert (await client.delete(path)).status_code == 422
    assert (
        await client.request("DELETE", path, json={"confirmation": "DELETE"})
    ).status_code == 409
    assert (
        await client.request(
            "DELETE", path, json={"confirmation": "DELETE", "detach_assigned": True}
        )
    ).status_code == 204
    assert (await client.get(f"/api/technicians/{person['id']}")).json()["calendar"] is None
    history = (await client.get(f"/api/technicians/{person['id']}/calendar-assignments")).json()
    assert history[0]["is_active"] is False
    assert history[0]["calendar_id"] is None
    assert history[0]["calendar_name"] == "DEMO - Calendar"


@pytest.mark.parametrize(
    "field,value", [("telegram_user_id", 123456789), ("telegram_group_chat_id", -100123456789)]
)
async def test_telegram_identifier_uniqueness(client, engine, field, value):
    first, second = await create(client), await create(client)
    async with engine.begin() as db:
        await db.execute(
            TelegramBinding.__table__.insert().values(
                technician_id=UUID(first["id"]), **{field: value}
            )
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                TelegramBinding.__table__.insert().values(
                    technician_id=UUID(second["id"]), **{field: value}
                )
            )


async def test_nullable_telegram_identifiers_can_repeat(client, engine):
    first, second = await create(client), await create(client)
    async with engine.begin() as db:
        for person in [first, second]:
            await db.execute(
                TelegramBinding.__table__.insert().values(technician_id=UUID(person["id"]))
            )


async def test_database_ssn_constraint(client, engine):
    person = await create(client)
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                text("UPDATE technicians SET ssn_last4='ABCD' WHERE id=:id"),
                {"id": UUID(person["id"])},
            )


async def test_concurrent_assignment_has_one_winner(client, engine):
    import asyncio

    first, second = await create(client), await create(client)
    local = await calendar(client)
    results = await asyncio.gather(
        *(
            client.put(
                f"/api/technicians/{person['id']}/calendar", json={"calendar_id": local["id"]}
            )
            for person in [first, second]
        )
    )
    assert sorted(response.status_code for response in results) == [200, 409]
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(CalendarAssignment)
                .where(CalendarAssignment.is_active.is_(True))
            )
            == 1
        )
