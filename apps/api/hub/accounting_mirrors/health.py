import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hub.accounting_mirrors.service import worker_state
from hub.core.config import Settings


async def main():
    settings = Settings()
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine)() as db:
            state = await worker_state(db)
        print(json.dumps({"accounting_mirror_worker": state}, sort_keys=True))
        return 0 if state == "RUNNING" else 1
    except Exception:
        print('{"error":"WORKER_HEALTH_UNAVAILABLE"}')
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
