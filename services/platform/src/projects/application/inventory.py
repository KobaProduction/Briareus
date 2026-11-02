"""Read bounded owner facts and current provider profiles before expiry."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.domain.inventory import (
    Inventory,
    InventorySnapshot,
    InventoryUser,
    InventoryUserReference,
    UserProfile,
)
from projects.domain.management import ManagementError


@dataclass(frozen=True, slots=True)
class InventoryQuery:
    issuer: str
    actor_uuid: UUID
    operator: bool
    team_uuid: UUID | None = None
    team_member: bool = False


class InventoryReader(Protocol):
    async def read(self, query: InventoryQuery) -> InventorySnapshot: ...


class ProfileReader(Protocol):
    async def profile(self, issuer: str, subject: str) -> UserProfile: ...


class ReadInventory:
    def __init__(
        self, reader: InventoryReader, profiles: ProfileReader, now: Callable[[], datetime]
    ) -> None:
        self._reader = reader
        self._profiles = profiles
        self._now = now

    async def execute(self, query: InventoryQuery, deadline: datetime) -> Inventory:
        if query.team_uuid is None and not query.operator:
            raise ManagementError(403, "PLATFORM_OPERATOR_REQUIRED")
        if query.team_uuid is not None and not (query.operator or query.team_member):
            raise ManagementError(403, "TEAM_MEMBERSHIP_REQUIRED")
        snapshot = await self._reader.read(query)
        gate = asyncio.Semaphore(8)

        async def describe(user: InventoryUserReference) -> InventoryUser:
            async with gate:
                profile = await self._profiles.profile(query.issuer, user.subject)
                return InventoryUser(
                    user.uuid,
                    user.role,
                    user.enabled and profile.enabled,
                    profile.name,
                    profile.email,
                )

        async with asyncio.timeout(6):
            users = await asyncio.gather(*(describe(user) for user in snapshot.users))
        if self._now() >= deadline:
            raise ManagementError(503, "PLATFORM_AUTHORITY_EXPIRED")
        return Inventory(tuple(users), snapshot.teams, snapshot.projects, snapshot.truncated)
