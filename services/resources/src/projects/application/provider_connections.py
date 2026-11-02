"""Bounded provider verification, independent of network and HTTP adapters."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from projects.application._transaction_binding import (
    _PlatformClockBinding,
    _TransactionClockBinding,
)
from projects.application.node_administration import PlatformActors
from projects.domain.connection_settings import ConnectionSettings
from projects.domain.node_administration import OperatorSelector, current_lease
from projects.domain.provider_connections import (
    ConnectionFailure,
    ConnectionRevision,
    ProviderCheck,
    ProviderProbe,
    require_connection_proof,
)
from runtime_peer.event_projection import EventPage
from runtime_peer.event_window import EventWindow
from service_runtime._reference_bindings import _VerifierBinding


class ConnectionEvents(Protocol):
    async def read(self, project_uuid: UUID, window: EventWindow) -> EventPage: ...


class AuthorizeConnections(_PlatformClockBinding[PlatformActors]):
    async def execute(self, selector: OperatorSelector) -> datetime:
        if (
            selector.actor_uuid.version != 4
            or selector.project_uuid.version != 4
            or not current_lease(selector.identity_expires_at, self._now())
        ):
            raise ConnectionFailure(403, "Current project identity required")
        found = await self._platform.read(selector)
        if found.status != 200:
            raise ConnectionFailure(
                403 if found.status == 403 else 503, "Current Platform source unavailable"
            )
        evidence = found.evidence
        if (
            evidence is None
            or evidence.issuer != selector.issuer
            or evidence.subject != selector.subject
            or evidence.actor_uuid != str(selector.actor_uuid)
            or evidence.project_uuid != str(selector.project_uuid)
            or "use_resources" not in evidence.permissions
            or not current_lease(evidence.expires_at, self._now())
        ):
            raise ConnectionFailure(403, "Current project membership required")
        if evidence.role != "operator":
            raise ConnectionFailure(403, "Platform operator required")
        expiry = min(evidence.expires_at, selector.identity_expires_at)
        require_connection_proof(expiry, self._now())
        return expiry


class ConnectionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    name: str
    alias: str
    provider: str
    base_url: str
    auth_type: str
    credential_configured: Literal[True] = True
    revision: int
    configuration: ConnectionSettings


class ConnectionItem(BaseModel):
    item: ConnectionSummary


class ConnectionPage(BaseModel):
    items: tuple[ConnectionSummary, ...]
    has_more: bool
    next_cursor: str | None


class DeletedConnection(BaseModel):
    deleted: Literal[True] = True


@dataclass(frozen=True)
class ConnectionCredential:
    token: str = field(repr=False)


@dataclass(frozen=True)
class ExistingConnection:
    summary: ConnectionSummary
    credential: ConnectionCredential
    deleted: bool = False


@dataclass(frozen=True)
class WriteConnection:
    action: Literal["create", "update", "delete"]
    identity: ConnectionRevision
    actor_uuid: UUID
    alias: str
    settings: ConnectionSettings | None
    credential: ConnectionCredential | None


class ConnectionSession(Protocol):
    async def page(self, project_uuid: UUID, cursor: str | None) -> ConnectionPage: ...
    async def find(
        self,
        identity: ConnectionRevision,
        *,
        lock: bool,
        credential: bool = False,
    ) -> ExistingConnection | None: ...
    async def create(self, command: WriteConnection, now: datetime) -> ConnectionSummary: ...
    async def update(self, command: WriteConnection, now: datetime) -> ConnectionSummary: ...
    async def delete(self, identity: ConnectionRevision, now: datetime) -> None: ...
    async def audit(self, command: WriteConnection, provider: str, revision: int) -> None: ...


class ConnectionTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[ConnectionSession]: ...


class ManageConnections(_TransactionClockBinding[ConnectionTransactions]):
    async def page(
        self, project_uuid: UUID, cursor: str | None, expiry: datetime
    ) -> ConnectionPage:
        async with self._transactions.transaction() as session:
            result = await session.page(project_uuid, cursor)
            require_connection_proof(expiry, self._now())
        return result

    async def existing(
        self,
        identity: ConnectionRevision,
        expiry: datetime,
        *,
        credential: bool = True,
    ) -> ExistingConnection:
        async with self._transactions.transaction() as session:
            found = await session.find(identity, lock=False, credential=credential)
            if found is None or found.deleted:
                raise ConnectionFailure(404, "Connection not found")
            require_connection_proof(expiry, self._now())
        return found

    async def write(
        self, command: WriteConnection, expiry: datetime
    ) -> ConnectionItem | DeletedConnection:
        command.identity.require_identifier()
        async with self._transactions.transaction() as session:
            found = await session.find(command.identity, lock=True)
            result = await self._write(session, command, found)
            provider = (
                result.item.provider
                if isinstance(result, ConnectionItem)
                else (found.summary.provider if found else "")
            )
            revision = (
                result.item.revision
                if isinstance(result, ConnectionItem)
                else (found.summary.revision + 1 if found else 0)
            )
            await session.audit(command, provider, revision)
            require_connection_proof(expiry, self._now())
        return result

    async def _write(
        self,
        session: ConnectionSession,
        command: WriteConnection,
        found: ExistingConnection | None,
    ) -> ConnectionItem | DeletedConnection:
        if command.action == "create":
            if found is not None:
                raise ConnectionFailure(409, "Connection already exists; refresh the list")
            return ConnectionItem(item=await session.create(command, self._now()))
        if found is None or found.deleted:
            raise ConnectionFailure(404, "Connection not found")
        command.identity.require_matches(
            found.summary.revision, deleting=command.action == "delete"
        )
        if command.action == "delete":
            await session.delete(command.identity, self._now())
            return DeletedConnection(deleted=True)
        if command.settings is None or command.settings.provider != found.summary.provider:
            raise ConnectionFailure(422, "Provider cannot change on an existing connection")
        return ConnectionItem(item=await session.update(command, self._now()))


class ProviderVerifier(Protocol):
    async def verify(self, probe: ProviderProbe) -> ProviderCheck: ...


class VerifyProviderConnection(_VerifierBinding[ProviderVerifier]):
    async def execute(self, probe: ProviderProbe, *, existing: bool = False) -> ProviderCheck:
        try:
            return await self._verifier.verify(probe)
        except (OSError, TimeoutError, ValueError):
            return ProviderCheck.unavailable(existing=existing)


@dataclass(frozen=True)
class PreparedConnectionWrite:
    action: Literal["verify", "create", "update"]
    selector: OperatorSelector
    connection_uuid: UUID | None
    expected_revision: int | None
    alias: str
    settings: ConnectionSettings
    credential: ConnectionCredential


@dataclass(frozen=True)
class VerificationRequired:
    pass


class VerifyAndSaveConnection:
    def __init__(
        self,
        authority: AuthorizeConnections,
        connections: ManageConnections,
        verifier: VerifyProviderConnection,
    ) -> None:
        self._authority, self._connections, self._verifier = authority, connections, verifier

    async def execute(
        self,
        command: PreparedConnectionWrite,
    ) -> ProviderCheck | ConnectionItem | DeletedConnection | VerificationRequired:
        checked = await self._verifier.execute(
            probe_from_settings(command.settings, command.credential.token)
        )
        expiry = await self._authority.execute(command.selector)
        if command.action == "verify":
            return checked
        if checked.status != "connected":
            return VerificationRequired()
        if command.connection_uuid is None:
            raise ConnectionFailure(422, "Connection UUID required")
        return await self._connections.write(
            WriteConnection(
                command.action,
                ConnectionRevision(
                    command.selector.project_uuid,
                    command.connection_uuid,
                    command.expected_revision,
                ),
                command.selector.actor_uuid,
                command.alias,
                command.settings,
                command.credential,
            ),
            expiry,
        )


class CheckExistingConnection:
    def __init__(
        self,
        authority: AuthorizeConnections,
        connections: ManageConnections,
        verifier: VerifyProviderConnection,
        now: Callable[[], datetime],
    ) -> None:
        self._authority, self._connections, self._verifier, self._now = (
            authority,
            connections,
            verifier,
            now,
        )

    async def execute(
        self, selector: OperatorSelector, identity: ConnectionRevision, expiry: datetime
    ) -> ProviderCheck:
        identity.require_identifier()
        existing = await self._connections.existing(identity, expiry)
        checked = await self._verifier.execute(
            probe_from_settings(existing.summary.configuration, existing.credential.token),
            existing=True,
        )
        await self._authority.execute(selector)
        require_connection_proof(expiry, self._now())
        return checked


def probe_from_settings(settings: ConnectionSettings, token: str) -> ProviderProbe:
    return ProviderProbe(
        settings.provider,
        settings.base_url,
        token,
        settings.auth_type,
        settings.external_id or "",
        settings.ca_cert_pem,
    )
