from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from hub.auth.models import ManagerSession, RateBucket
from hub.auth.security import now
from hub.google_calendar.models import GoogleOAuthAttempt
from hub.integrations.models import TelegramBinding
from hub.ops.service import cleanup_expired
from hub.schedule_delivery.models import ScheduleDeliverySetting
from hub.technicians.models import Technician
from hub.telegram.models import TelegramProcessedUpdate, TelegramWorkerState
from tests.test_api import calendar, create


async def test_profile_version_is_database_owned_and_delete_is_disabled(client, engine):
    profile = await create(client)
    assert profile["record_version"] == 1

    changed = await client.patch(
        f"/api/technicians/{profile['id']}",
        json={
            "expected_record_version": profile["record_version"],
            "first_name": "Changed",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["record_version"] == 2

    stale = await client.patch(
        f"/api/technicians/{profile['id']}",
        json={"expected_record_version": 1, "last_name": "Stale"},
    )
    assert stale.status_code == 409

    deleted = await client.request(
        "DELETE",
        f"/api/technicians/{profile['id']}",
        json={"confirmation": "DELETE", "expected_record_version": 2},
    )
    assert deleted.status_code == 409
    assert "deactivate" in deleted.text.lower()

    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                text("UPDATE technicians SET record_version=99 WHERE id=:id"),
                {"id": profile["id"]},
            )
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(text("DELETE FROM technicians WHERE id=:id"), {"id": profile["id"]})


@pytest.mark.parametrize(
    "column,value",
    [
        ("photo_url", "https://example.invalid/photo.png"),
        ("driver_license_id", "DEMO-ONLY"),
        ("ssn_last4", "0123"),
    ],
)
async def test_database_rejects_new_pilot_profile_data(engine, column, value):
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                text(
                    f"INSERT INTO technicians "
                    f"(id, first_name, last_name, status, {column}) "
                    f"VALUES (:id, 'Pilot', 'Test', 'ACTIVE', :value)"
                ),
                {"id": uuid4(), "value": value},
            )


async def test_readiness_dependencies_increment_once_per_transaction(client, engine):
    profile = await create(client)
    demo = await calendar(client, "DEMO - Version Boundary")
    assigned = await client.put(
        f"/api/technicians/{profile['id']}/calendar",
        json={"calendar_id": demo["id"]},
    )
    assert assigned.status_code == 200
    after_assignment = (await client.get(f"/api/technicians/{profile['id']}")).json()
    assert after_assignment["record_version"] == profile["record_version"] + 1

    identifier = UUID(profile["id"])
    async with engine.begin() as db:
        await db.execute(
            TelegramBinding.__table__.insert().values(
                technician_id=identifier,
                private_status="PENDING",
                private_generation=1,
                bot_id=10,
            )
        )
        await db.execute(
            ScheduleDeliverySetting.__table__.insert().values(
                technician_id=identifier, enabled=True
            )
        )
    async with engine.connect() as db:
        current = await db.scalar(
            select(Technician.record_version).where(Technician.id == identifier)
        )
    assert current == after_assignment["record_version"] + 1

    async with engine.begin() as db:
        await db.execute(
            text("UPDATE calendars SET availability='UNAVAILABLE' WHERE id=:id"),
            {"id": demo["id"]},
        )
    async with engine.connect() as db:
        final = await db.scalar(
            select(Technician.record_version).where(Technician.id == identifier)
        )
    assert final == current + 1


async def test_pilot_metadata_cleanup_is_bounded_and_offset_safe(app, client):
    stamp = now()
    async with app.state.session_factory() as db, db.begin():
        manager_session = await db.scalar(select(ManagerSession))
        db.add_all(
            [
                GoogleOAuthAttempt(
                    state_hash="a" * 64,
                    manager_id=manager_session.manager_id,
                    session_id=manager_session.id,
                    encrypted_verifier=None,
                    created_at=stamp - timedelta(days=8),
                    expires_at=stamp - timedelta(days=8),
                    mode="CONNECT",
                ),
                GoogleOAuthAttempt(
                    state_hash="b" * 64,
                    manager_id=manager_session.manager_id,
                    session_id=manager_session.id,
                    encrypted_verifier="v1:synthetic",
                    created_at=stamp - timedelta(days=8),
                    expires_at=stamp - timedelta(days=8),
                    mode="CONNECT",
                ),
                TelegramWorkerState(bot_id=10, next_update_id=102, status="STOPPED"),
                TelegramProcessedUpdate(
                    bot_id=10,
                    update_id=100,
                    outcome="IGNORED",
                    processed_at=stamp - timedelta(days=8),
                ),
                TelegramProcessedUpdate(
                    bot_id=10,
                    update_id=102,
                    outcome="IGNORED",
                    processed_at=stamp - timedelta(days=8),
                ),
                TelegramProcessedUpdate(
                    bot_id=11,
                    update_id=50,
                    outcome="IGNORED",
                    processed_at=stamp - timedelta(days=8),
                ),
                RateBucket(
                    key_hash="c" * 64,
                    count=1,
                    window_start=stamp - timedelta(days=8),
                ),
            ]
        )
    async with app.state.session_factory() as db, db.begin():
        result = await cleanup_expired(db, apply=True, settings=app.state.settings)
        assert result.expired_oauth_verifiers == 1
        assert result.expired_oauth_attempt_metadata == 1
        assert result.expired_telegram_processed_updates == 1
        assert result.expired_rate_buckets == 1
    async with app.state.session_factory() as db:
        attempts = (await db.scalars(select(GoogleOAuthAttempt))).all()
        assert len(attempts) == 1 and attempts[0].encrypted_verifier is None
        assert await db.get(TelegramProcessedUpdate, (10, 100)) is None
        assert await db.get(TelegramProcessedUpdate, (10, 102)) is not None
        assert await db.get(TelegramProcessedUpdate, (11, 50)) is not None
    async with app.state.session_factory() as db, db.begin():
        second = await cleanup_expired(db, apply=True, settings=app.state.settings)
        assert second.expired_oauth_attempt_metadata == 1
