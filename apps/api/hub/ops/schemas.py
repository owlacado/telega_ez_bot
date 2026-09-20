from typing import Literal

from pydantic import BaseModel


class ComponentHealth(BaseModel):
    state: Literal[
        "PASS", "BLOCK", "RUNNING", "STALE", "STOPPED", "ERROR", "MISSING", "DISABLED"
    ]
    message: str


class QueueCounts(BaseModel):
    pending: int = 0
    processing: int = 0
    failed: int = 0
    ambiguous: int = 0


class OperationsHealth(BaseModel):
    status: Literal["PASS", "WARN", "BLOCK"]
    app_version: str
    release_commit: str
    database: ComponentHealth
    migration: ComponentHealth
    telegram_worker: ComponentHealth
    schedule_worker: ComponentHealth
    mirror_worker: ComponentHealth
    google_configuration: ComponentHealth
    queues: dict[str, QueueCounts]


class CleanupResult(BaseModel):
    dry_run: bool
    expired_form_snapshots: int
    expired_oauth_verifiers: int
    expired_schedule_payloads: int
