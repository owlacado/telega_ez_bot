"""Destructive round-trip verification is restricted to the disposable test database."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
url = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://hub:hub_test_only@127.0.0.1:5437/technician_hub_test"
)
parsed = make_url(url)
if parsed.database != "technician_hub_test" or parsed.host not in {
    "127.0.0.1",
    "localhost",
    "test-db",
}:
    raise SystemExit(
        "Refusing migration round-trip outside the local technician_hub_test database."
    )
env = {**os.environ, "DATABASE_URL": url}
for arguments in [
    ("upgrade", "head"),
    ("downgrade", "base"),
    ("upgrade", "head"),
    ("check",),
    ("current",),
]:
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments], cwd=root / "apps/api", env=env, check=True
    )
print("Migration upgrade / downgrade / upgrade and metadata drift validation passed.")
