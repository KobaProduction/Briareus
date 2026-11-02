"""Verified Unix operator and owner SQL adapters for legacy first-admin setup."""

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied
from identity._operator_channel import UnixFirstAdminOperatorGate
from identity._persistence import InvitationRow
from identity.application.first_admin import SetupTransaction
from identity.infrastructure.registration import RegistrationHost


class SetupHost(RegistrationHost, Protocol):
    database: PlatformDatabase


@dataclass(frozen=True)
class LegacySetupOperator:
    gate: UnixFirstAdminOperatorGate | None
    connection: socket.socket

    def require(self) -> None:
        if self.gate is None:
            raise AccessDenied("first-admin verified operator channel is not configured")
        self.gate.verify_accepted_peer(self.connection)


@dataclass(frozen=True)
class SqlSetupTransaction:
    host: SetupHost
    tx: AsyncSession

    async def lock_claimed(self) -> bool:
        bootstrap = await self.host.repository.lock_bootstrap(self.tx)
        return bootstrap.first_superuser_claimed

    async def active_superusers(self) -> bool:
        return bool(await self.host.repository.list_active_superusers(self.tx))

    async def revoke_pending(self, now: datetime) -> None:
        await self.tx.execute(
            update(InvitationRow)
            .where(
                InvitationRow.kind == "system",
                InvitationRow.used_at.is_(None),
                InvitationRow.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def issue(self, digest: str, expires_at: datetime) -> None:
        self.tx.add(
            InvitationRow(
                id=uuid4(),
                token_digest=digest,
                kind="system",
                expires_at=expires_at,
            )
        )
        await self.tx.flush()
        self.host._record_local_security_event(
            self.tx,
            actor_id=None,
            target_id=UUID(int=0),
            event="identity.bootstrap_setup_issued",
            credential_version=0,
        )


@dataclass(frozen=True)
class SqlSetupTransactions:
    host: SetupHost

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SetupTransaction]:
        async with self.host.database.transaction() as tx:
            yield SqlSetupTransaction(self.host, tx)
