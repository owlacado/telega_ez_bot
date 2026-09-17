"""Repeatable, destructive profiling on a guarded disposable PostgreSQL database."""

import asyncio
import json
import os
import secrets
from statistics import median
from time import perf_counter
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from hub.auth.models import Manager
from hub.auth.service import create_manager
from hub.calendars.models import Calendar, CalendarAssignment
from hub.core.config import Settings
from hub.main import create_app
from hub.technicians.models import Technician
from sqlalchemy import delete, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main():
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.database != "technician_hub_test" or parsed.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Profiling requires the disposable local technician_hub_test database.")
    engine = create_async_engine(url)
    results = []
    password = secrets.token_urlsafe(24)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        manager = await create_manager(db, "profile-" + uuid4().hex, password)
    try:
        for size in [10, 50, 250]:
            async with engine.begin() as db:
                await db.execute(text("TRUNCATE technicians, calendars CASCADE"))
                people = [
                    {"id": uuid4(), "first_name": "Audit", "last_name": f"Person{i:03}"}
                    for i in range(size)
                ]
                calendars = [{"id": uuid4(), "name": f"Audit calendar {i:03}"} for i in range(size)]
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
                        }
                        for t, c in zip(people, calendars, strict=True)
                    ],
                )
            app = create_app(Settings(database_url=url, app_env="test"))
            async with app.router.lifespan_context(app):
                count = 0

                def on_query(*args):
                    nonlocal count
                    count += 1

                event.listen(
                    app.state.session_factory.kw["bind"].sync_engine,
                    "before_cursor_execute",
                    on_query,
                )
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://127.0.0.1:3000",
                    headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
                ) as client:
                    login = await client.post(
                        "/api/auth/login", json={"username": manager.username, "password": password}
                    )
                    assert login.status_code == 200
                    for endpoint in ["/api/technicians", "/api/calendars"]:
                        samples, queries = [], []
                        for _ in range(4):
                            count = 0
                            start = perf_counter()
                            response = await client.get(endpoint)
                            samples.append((perf_counter() - start) * 1000)
                            queries.append(count)
                            assert response.status_code == 200 and len(response.json()) == size
                        results.append(
                            {
                                "records": size,
                                "endpoint": endpoint,
                                "queries": queries,
                                "cold_ms": round(samples[0], 2),
                                "warm_median_ms": round(median(samples[1:]), 2),
                                "response_bytes": len(response.content),
                            }
                        )
                        assert max(queries) <= 6, "Unexpected query growth / N+1"
    finally:
        async with engine.begin() as db:
            await db.execute(text("TRUNCATE technicians, calendars CASCADE"))
            await db.execute(delete(Manager).where(Manager.id == manager.id))
        await engine.dispose()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
