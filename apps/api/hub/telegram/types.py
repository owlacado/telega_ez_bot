from dataclasses import dataclass, field
from typing import Literal

Purpose = Literal["PRIVATE_TELEGRAM", "WORK_GROUP"]


@dataclass(frozen=True)
class BotIdentity:
    id: int
    username: str


@dataclass(frozen=True)
class Member:
    status: str
    is_member: bool = False
    is_anonymous: bool = False
    can_send_messages: bool = True

    @property
    def present(self) -> bool:
        return self.status in {"creator", "administrator", "member"} or (
            self.status == "restricted" and self.is_member
        )


@dataclass(frozen=True)
class GroupChecks:
    initiator_admin: bool
    bot_admin: bool
    technician_member: bool
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.initiator_admin
            and self.bot_admin
            and self.technician_member
            and self.error is None
        )


@dataclass(frozen=True)
class TrustedEvent:
    update_id: int
    kind: str
    chat_id: int | None = None
    chat_type: str | None = None
    user_id: int | None = None
    user_is_bot: bool = False
    anonymous: bool = False
    display_name: str | None = None
    username: str | None = None
    chat_title: str | None = None
    command: str | None = None
    payload: str | None = field(default=None, repr=False)
    callback_query_id: str | None = field(default=None, repr=False)
    message_id: int | None = None
    member_user_id: int | None = None
    member_status: str | None = None
    member_present: bool = False
    migrated_chat_id: int | None = None


SAFE_PROVIDER_CODES = frozenset(
    {
        "POLLING_CONFLICT",
        "INVALID_BOT_CREDENTIALS",
        "ACCESS_DENIED",
        "CHAT_UNAVAILABLE",
        "RATE_LIMITED",
        "REQUEST_REJECTED",
        "NETWORK_UNCERTAIN",
        "PROVIDER_UNAVAILABLE",
        "BOT_NOT_CONFIGURED",
        "BOT_IDENTITY_MISMATCH",
        "EXISTING_WEBHOOK_REFUSED",
        "PROCESSING_FAILED",
    }
)


class ProviderError(Exception):
    def __init__(self, code: str, *, retry_after: int = 0):
        code = code if code in SAFE_PROVIDER_CODES else "PROCESSING_FAILED"
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after
