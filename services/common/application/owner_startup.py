"""Startup and repeated readiness of exactly one authoritative schema owner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from common.application.owner_ingress import AttestOwnerIngress
from common.domain.owner_runtime import OwnerName
from common.owner_startup_diagnostics import Phase

RuntimeState = Literal[
    "not_started", "database_wait", "migrating", "security_pending", "ready", "failed", "stopped"
]


@dataclass(frozen=True, slots=True)
class OwnerRuntimeStatus:
    owner: OwnerName
    state: RuntimeState = "not_started"
    revision: str | None = None
    table_count: int = 0
    security_ready: bool = False


@dataclass(frozen=True, slots=True)
class OwnerSchemaStatus:
    revision: str
    tables: int


class OwnerSchemaLifecycle(Protocol):
    @property
    def available(self) -> bool: ...

    def initialize(self, phase_change: Callable[[Phase], None]) -> None: ...

    async def migrate(self, phase_change: Callable[[Phase], None]) -> None: ...

    async def verify(self, *, fresh_settings: bool = False) -> OwnerSchemaStatus: ...

    async def close(self) -> None: ...


class OwnerStartup:
    def __init__(
        self, owner: OwnerName, schema: OwnerSchemaLifecycle, ingress: AttestOwnerIngress
    ) -> None:
        self.owner = owner
        self.schema = schema
        self.ingress = ingress
        self.phase: Phase = "settings"
        self.status = OwnerRuntimeStatus(owner)

    def _phase_change(self, value: Phase) -> None:
        self.phase = value

    async def start(self) -> None:
        self.status = OwnerRuntimeStatus(self.owner, "database_wait")
        self.phase = "settings"
        self.schema.initialize(self._phase_change)
        self.phase = "alembic_upgrade"
        self.status = OwnerRuntimeStatus(self.owner, "migrating")
        await self.schema.migrate(self._phase_change)
        self.phase = "owner_schema_verify"
        observed = await self.schema.verify()
        self.status = OwnerRuntimeStatus(
            self.owner, "security_pending", observed.revision, observed.tables
        )
        self.phase = "ingress_attestation"
        if self.ingress.verifier is not None:
            if not await self.ingress.execute():
                raise RuntimeError("owner ingress trust attestation denied")
            self.status = OwnerRuntimeStatus(
                self.owner, "ready", observed.revision, observed.tables, True
            )

    async def require_ready(self) -> OwnerRuntimeStatus:
        if (
            not self.status.security_ready
            or self.status.state != "ready"
            or not self.schema.available
        ):
            raise OwnerNotReady("authoritative owner not ready")
        try:
            if not await self.ingress.execute():
                raise RuntimeError("trusted ingress expired or revoked")
            await self.schema.verify(fresh_settings=True)
        except Exception:
            raise OwnerNotReady("authoritative owner schema or ingress unavailable") from None
        return self.status

    def failed(self) -> None:
        self.status = OwnerRuntimeStatus(self.owner, "failed")

    async def close(self) -> None:
        await self.schema.close()
        self.status = OwnerRuntimeStatus(self.owner, "stopped")


class OwnerNotReady(Exception):
    """A fixed public readiness reason, without underlying provider diagnostics."""
