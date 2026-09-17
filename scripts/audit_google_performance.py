"""Repeatable Google audit profiling; destructive only on an explicit loopback test DB."""

import asyncio
import json
import os
import secrets
from statistics import median
from time import perf_counter
from uuid import uuid4

from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from hub.auth.service import create_manager
from hub.calendars.models import Calendar, CalendarAssignment
from hub.core.config import Settings
from hub.core.secrets import SecretCipher
from hub.google_calendar.fake import FakeCalendarProvider
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import DiscoveredCalendar
from hub.main import create_app
from hub.technicians.models import Technician
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main():
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.database != "technician_hub_test" or parsed.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Only an explicit disposable loopback technician_hub_test is allowed.")
    engine = create_async_engine(url, hide_parameters=True)
    key = Fernet.generate_key().decode()
    output = []
    for size in [10, 50, 250, 1000]:
        async with engine.begin() as db:
            await db.execute(
                text(
                    "TRUNCATE technicians, calendars, managers, rate_buckets, audit_events, "
                    "google_oauth_attempts, calendar_connections CASCADE"
                )
            )
        password = secrets.token_urlsafe(24)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            manager = await create_manager(db, "audit-performance", password)
            connection = CalendarConnection(
                account_key="audit-primary",
                account_label="Audit",
                encrypted_refresh_token=SecretCipher(key).encrypt("fake-refresh-only"),
                granted_scopes=[],
            )
            db.add(connection)
            await db.flush()
            connection_id = connection.id
            await db.commit()
        people = [
            {"id": uuid4(), "first_name": "Audit", "last_name": f"Person{i:04}"}
            for i in range(size)
        ]
        calendars = [
            {
                "id": uuid4(),
                "name": f"Calendar {i:04}",
                "source": "GOOGLE",
                "provider_connection_id": connection_id,
                "provider_calendar_id": "audit-primary" if i == 0 else str(i),
                "primary": i == 0,
            }
            for i in range(size)
        ]
        async with engine.begin() as db:
            await db.execute(Technician.__table__.insert(), people)
            await db.execute(Calendar.__table__.insert(), calendars)
            await db.execute(
                CalendarAssignment.__table__.insert(),
                [
                    {
                        "id": uuid4(),
                        "technician_id": t["id"],
                        "calendar_id": c["id"],
                        "calendar_name": c["name"],
                        "is_active": active,
                    }
                    for t, c in zip(people, calendars, strict=True)
                    for active in [False, False, False, True]
                ],
            )
        app = create_app(
            Settings(
                database_url=url,
                app_env="test",
                google_mode="fake",
                google_calendar_credential_encryption_key=key,
            )
        )
        async with app.router.lifespan_context(app):
            fake = FakeCalendarProvider()
            fake.calendars = [
                DiscoveredCalendar(c["provider_calendar_id"], c["name"], primary=c["primary"])
                for c in calendars
            ]
            app.state.google_provider = fake
            metrics = {"queries": 0, "calendar_update_rows": 0}

            def query(conn, cursor, statement, parameters, context, many, metrics=metrics):
                metrics["queries"] += 1
                if statement.startswith("UPDATE calendars SET"):
                    metrics["calendar_update_rows"] += len(parameters) if many else 1

            event.listen(app.state.engine.sync_engine, "before_cursor_execute", query)
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://127.0.0.1:3000",
                headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
            ) as client:
                login = await client.post(
                    "/api/auth/login", json={"username": manager.username, "password": password}
                )
                client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
                routes = {
                    "calendars": ["/api/calendars"],
                    "technicians": ["/api/technicians"],
                    "detail": [f"/api/technicians/{people[0]['id']}"],
                    "dashboard": ["/api/calendars", "/api/technicians"],
                    "search": ["/api/technicians?q=Person0001"],
                    "connection_status": ["/api/calendar-connections/google"],
                }
                for name, paths in routes.items():
                    times, counts = [], []
                    for _ in range(3):
                        metrics["queries"] = 0
                        start = perf_counter()
                        responses = [await client.get(path) for path in paths]
                        assert all(r.status_code == 200 for r in responses)
                        times.append((perf_counter() - start) * 1000)
                        counts.append(metrics["queries"])
                    output.append(
                        {
                            "size": size,
                            "operation": name,
                            "median_ms": round(median(times), 2),
                            "queries": counts[-1],
                            "response_bytes": sum(len(r.content) for r in responses),
                        }
                    )
                for label in ["scan", "identical_rescan"]:
                    metrics.update(queries=0, calendar_update_rows=0)
                    start = perf_counter()
                    response = await client.post("/api/calendar-connections/google/scan")
                    assert response.status_code == 200
                    output.append(
                        {
                            "size": size,
                            "operation": label,
                            "ms": round((perf_counter() - start) * 1000, 2),
                            **metrics,
                        }
                    )
    await engine.dispose()
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
