"""Future provider ports. No implementations or calls exist in Stage 0."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


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
    async def connection(self, technician_id: UUID) -> ProviderConnection: ...


class CalendarProvider(Protocol):
    async def connection(self, technician_id: UUID) -> ProviderConnection: ...


class AccountingProvider(Protocol):
    async def connection(self, technician_id: UUID) -> ProviderConnection: ...


class GpsProvider(Protocol):
    async def connection(self, technician_id: UUID) -> ProviderConnection: ...
