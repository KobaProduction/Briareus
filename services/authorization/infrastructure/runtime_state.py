"""Private listener lifecycle and concrete composition of per-request runtime ports."""

from __future__ import annotations

import os
import stat
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import partial

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request

from authorization._approval_read_api import ApprovalListReader
from authorization._idempotency import IdempotentCommandExecutor
from authorization._rauthy_access_commands import AccessRauthyCommandService
from authorization.application.runtime_dispatch import DispatchRuntime
from authorization.application.runtime_effects import RuntimeEffectPreparation
from authorization.infrastructure.runtime_handlers import (
    PlatformRuntimeActor,
    RuntimePeers,
    RuntimeServices,
    RuntimeSessionHandlers,
)
from authorization.infrastructure.runtime_resources import (
    JwtRuntimeEffectSigner,
    PeerRuntimePlacements,
    RuntimeResourceHandlers,
    SqlRuntimeGrantUnitOfWork,
)
from authorization.presentation.runtime_attestor import HumanAttestor
from common.owner_migrations import verify_owner
from common.owner_runtime import VerifiedOwnerIngress
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase

_utc_now = partial(datetime.now, UTC)


class UnixIngress:
    def __init__(self, path: str) -> None:
        self.path = path

    async def verify_running_ingress(self) -> VerifiedOwnerIngress:
        if not hasattr(os, "getuid"):
            raise ValueError("Private Access listener unavailable")
        info = os.stat(self.path)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o007:
            raise ValueError("Private Access listener unavailable")
        return VerifiedOwnerIngress(
            "access",
            "unix-peer",
            True,
            datetime.now(UTC) + timedelta(seconds=10),
        )


class RuntimeState:
    def __init__(self, peers: RuntimePeers, encryption_key: str) -> None:
        self.peers = peers
        self.encryption_key = encryption_key
        self.services: RuntimeServices | None = None

    def database(self) -> PlatformDatabase | None:
        return self.services.database if self.services is not None else None

    @asynccontextmanager
    async def lifespan(
        self,
        app: FastAPI,
        owner_lifespan: Callable[[FastAPI], AbstractAsyncContextManager[object]],
    ) -> AsyncIterator[None]:
        async with owner_lifespan(app):
            database = PlatformDatabase(OwnerDatabaseSettings(owner="access"))
            try:
                await verify_owner(database, OwnerDatabaseSettings(owner="access"))
                attestor = HumanAttestor()
                commands = AccessRauthyCommandService(
                    database=database,
                    idempotency=IdempotentCommandExecutor(database, self.encryption_key),
                    attestor=attestor,
                )
                reader = ApprovalListReader(database=database, attestor=attestor)
                self.services = RuntimeServices(
                    database, commands, reader, attestor, self.encryption_key
                )
                yield
            finally:
                self.services = None
                await database.close()
                for peer in (
                    self.peers.platform,
                    self.peers.terminal,
                    self.peers.files,
                    self.peers.web,
                    self.peers.node_resources,
                ):
                    if peer is not None:
                        await peer.close()


class RuntimeDispatcherFactory:
    def __init__(self, state: RuntimeState, effect_key: Ed25519PrivateKey | None) -> None:
        self._state = state
        self._effect_key = effect_key

    def for_request(self, request: Request) -> DispatchRuntime | None:
        services = self._state.services
        if services is None:
            return None
        now = _utc_now
        peers = self._state.peers
        sessions = RuntimeSessionHandlers(request, services, peers)
        preparation = RuntimeEffectPreparation(
            PeerRuntimePlacements(peers),
            SqlRuntimeGrantUnitOfWork(services.database),
            JwtRuntimeEffectSigner(self._effect_key),
            now,
        )
        return DispatchRuntime(
            PlatformRuntimeActor(peers.platform),
            sessions,
            RuntimeResourceHandlers(peers, preparation),
            sessions,
            now,
        )
