"""Prepare one bounded effect under current Platform, Cedar and session authority."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from authorization.domain.runtime_policy import (
    RuntimeAccessDenied,
    RuntimeActor,
    RuntimePlacement,
    effect_expiry,
)


@dataclass(frozen=True, slots=True)
class RuntimePermit:
    permit: str


@dataclass(frozen=True, slots=True)
class RuntimeEffectCall:
    tool: str
    arguments_digest: str
    agent_session_uuid: UUID
    expected_grant_revision: int
    operation_uuid: UUID

    def __post_init__(self) -> None:
        if (
            self.agent_session_uuid.version != 4
            or self.operation_uuid.version != 4
            or self.expected_grant_revision < 1
        ):
            raise ValueError("Invalid terminal effect")


@dataclass(frozen=True, slots=True)
class RuntimeEffectConfig:
    action: str
    kind: str
    audience: str
    lease_seconds: int


EFFECTS = {
    "terminal": RuntimeEffectConfig("terminal.execute", "workspace", "briareus:terminal-worker", 5),
    "files": RuntimeEffectConfig("files.read", "workspace_path", "briareus:files", 5),
    "web": RuntimeEffectConfig("web.access", "browser_session", "briareus:web", 20),
}


@dataclass(frozen=True, slots=True)
class RuntimeGrant:
    expires_at: datetime


class RuntimePlacementPort(Protocol):
    async def inspect(self, actor: RuntimeActor, hand: str) -> RuntimePlacement: ...


class RuntimeGrantTransaction(Protocol):
    async def require_grant(
        self,
        actor: RuntimeActor,
        placement: RuntimePlacement,
        call: RuntimeEffectCall,
        config: RuntimeEffectConfig,
    ) -> RuntimeGrant: ...


class RuntimeGrantUnitOfWork(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[RuntimeGrantTransaction]: ...


class RuntimeEffectSigner(Protocol):
    @property
    def configured(self) -> bool: ...

    def sign(
        self,
        actor: RuntimeActor,
        placement: RuntimePlacement,
        call: RuntimeEffectCall,
        config: RuntimeEffectConfig,
        *,
        issued_at: int,
        expires_at: int,
    ) -> str: ...


class RuntimeEffectPreparation:
    def __init__(
        self,
        placements: RuntimePlacementPort,
        grants: RuntimeGrantUnitOfWork,
        signer: RuntimeEffectSigner,
        now: Callable[[], datetime],
    ) -> None:
        self._placements = placements
        self._grants = grants
        self._signer = signer
        self._now = now

    async def prepare(
        self, actor: RuntimeActor, hand: str, command: RuntimeEffectCall
    ) -> RuntimePermit:
        config = EFFECTS.get(hand)
        if config is None:
            raise ValueError("Runtime hand unavailable")
        placement = await self._placements.inspect(actor, hand)
        placement.require_project(actor.project_uuid)
        call = command
        if call.tool not in placement.tools or not self._signer.configured:
            raise ValueError("Invalid terminal effect")
        async with self._grants.transaction() as tx:
            grant = await tx.require_grant(actor, placement, call, config)
            now = self._now()
            actor.require_active(now)
            issued_at = int(now.timestamp())
            expiry = effect_expiry(
                now_seconds=issued_at,
                lease_seconds=config.lease_seconds,
                actor_expires_at=actor.expires_at,
                session_expires_at=grant.expires_at,
            )
            permit = self._signer.sign(
                actor,
                placement,
                call,
                config,
                issued_at=issued_at,
                expires_at=expiry,
            )
        if not permit:
            raise RuntimeAccessDenied("Current effect permit unavailable")
        return RuntimePermit(permit)
