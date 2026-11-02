"""Exchange at most once, merge only while the original source generation survives."""

from dataclasses import dataclass
from typing import Protocol

from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
)
from control_panel_api.domain.resource_escrow import (
    EscrowSnapshot,
    ResourceCredentialUnavailable,
    valid_derived,
)


@dataclass(frozen=True, slots=True)
class ResourceSelection:
    hand: str
    audience: str
    primary: str
    allowed: frozenset[str]


class ResourceSessions(Protocol):
    async def identity(self, ticket: str) -> VerifiedOidcIdentity | None: ...

    async def primary(
        self, ticket: str, identity: VerifiedOidcIdentity, audience: str
    ) -> PrivateOidcResourceCredential | None: ...

    async def read(self, ticket: str, allowed: frozenset[str]) -> EscrowSnapshot | None: ...

    async def commit(
        self, ticket: str, snapshot: EscrowSnapshot, resource: PrivateOidcResourceCredential
    ) -> bool: ...

    async def delete(self, ticket: str) -> None: ...


class ResourceExchange(Protocol):
    async def exchange(
        self, *, source: PrivateOidcResourceCredential, identity: VerifiedOidcIdentity, hand: str
    ) -> PrivateOidcResourceCredential: ...


class ResolveResourceCredential:
    def __init__(self, sessions: ResourceSessions, broker: ResourceExchange | None) -> None:
        self._sessions, self._broker = sessions, broker

    async def execute(
        self, ticket: str, selection: ResourceSelection
    ) -> PrivateOidcResourceCredential | None:
        identity = await self._sessions.identity(ticket)
        if identity is None:
            return None
        source = await self._sessions.primary(ticket, identity, selection.primary)
        if source is None or selection.hand == "files":
            return source
        if self._broker is None:
            raise ResourceCredentialUnavailable("Resource broker is not configured")
        snapshot = await self._sessions.read(ticket, selection.allowed)
        if snapshot is None:
            return None
        cached = snapshot.cached(identity, selection.audience)
        if cached is not None:
            return cached
        if not snapshot.derives_from(identity, source):
            return None
        try:
            resource = await self._broker.exchange(
                source=source, identity=identity, hand=selection.hand
            )
            if not valid_derived(resource, identity, source, selection.audience):
                raise ResourceCredentialUnavailable("Resource broker identity binding invalid")
            return await self._merge(ticket, selection, snapshot, resource, identity, source)
        except OidcIdentityRejected:
            await self._sessions.delete(ticket)
            raise

    async def _merge(
        self,
        ticket: str,
        selection: ResourceSelection,
        snapshot: EscrowSnapshot,
        resource: PrivateOidcResourceCredential,
        identity: VerifiedOidcIdentity,
        source: PrivateOidcResourceCredential,
    ) -> PrivateOidcResourceCredential | None:
        for _ in range(4):
            committed = await self._sessions.commit(ticket, snapshot, resource)
            fresh = await self._sessions.read(ticket, selection.allowed)
            if fresh is None:
                return None
            cached = fresh.cached(identity, selection.audience)
            if cached is not None or committed:
                return cached
            if not fresh.derives_from(identity, source):
                return None
            snapshot = fresh
        raise ResourceCredentialUnavailable("Private resource escrow changed concurrently")
