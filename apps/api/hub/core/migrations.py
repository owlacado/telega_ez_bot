"""Read the release migration graph without running env.py or accessing a database."""

from pathlib import Path

from alembic.script import ScriptDirectory

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[2] / "migrations"


class ReleaseMigrationError(Exception):
    """The packaged release does not have one valid migration head."""


def release_migration_head() -> str:
    # Resolve from this release's source, never cwd, a DB value or a copied revision.
    # A fresh ScriptDirectory also makes newly added migrations visible in tests/dev.
    try:
        heads = ScriptDirectory(str(MIGRATIONS_DIRECTORY)).get_heads()
        if len(heads) != 1:
            raise ReleaseMigrationError()
        return heads[0]
    except Exception:
        raise ReleaseMigrationError("Release migration graph must have exactly one head.") from None
