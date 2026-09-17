from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.models import AuditEvent


def audit(
    db: AsyncSession,
    action: str,
    target_id: UUID | None = None,
    *,
    actor_id: UUID | None = None,
    outcome: str = "SUCCESS",
    actor_kind: str = "MANAGER",
) -> None:
    # Deliberately no free-form payload, names, provider IDs, secrets, or message text.
    db.add(
        AuditEvent(
            actor_id=actor_id,
            actor_kind=actor_kind,
            action=action,
            target_id=target_id,
            outcome=outcome,
        )
    )
