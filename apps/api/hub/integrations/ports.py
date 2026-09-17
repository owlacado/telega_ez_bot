"""Provider boundaries; only Telegram has an explicitly enabled Stage 1 adapter."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from hub.telegram.types import BotIdentity, Member, TrustedEvent


class VehicleLocationState(StrEnum):
    ACTIVE_TRIP = "ACTIVE_TRIP"
    LAST_KNOWN_STOP = "LAST_KNOWN_STOP"
    NO_DATA = "NO_DATA"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProviderConnection:
    technician_id: UUID
    status: str


class TelegramProvider(Protocol):
    async def initialize(self) -> BotIdentity: ...
    async def webhook_configured(self) -> bool: ...
    async def updates(self, offset: int | None) -> list[TrustedEvent]: ...
    async def member(self, chat_id: int, user_id: int) -> Member: ...
    async def send(self, chat_id: int, message: str) -> int: ...
    async def close(self) -> None: ...


class CalendarProvider(Protocol):
    async def connection(self, technician_id: UUID) -> ProviderConnection: ...


class AccountingProvider(Protocol):
    async def connection(self, technician_id: UUID) -> ProviderConnection: ...


class GpsProvider(Protocol):
    async def connection(self, technician_id: UUID) -> ProviderConnection: ...
