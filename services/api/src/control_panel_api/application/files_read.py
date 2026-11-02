"""Read bytes only after independent owner approval and final non-renewable authority checks."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from control_panel_api.domain.files_read import (
    FilesContentDenied,
    FilesReadRequest,
    PrivateFilesReadCommand,
    VerifiedPrivateFilesRead,
    files_authority_continues,
    files_selector,
    files_session_continues,
    project_allows_read,
    valid_owner_read,
)
from control_panel_api.domain.oidc_identity import (
    OidcSessionStoreUnavailable,
    PrivateOidcResourceCredential,
)
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_authority import PanelOidcSession


@dataclass(frozen=True, slots=True)
class FilesReadFailure:
    status: int
    code: str


@dataclass(frozen=True, slots=True)
class FilesReadDocument:
    path: str
    size_bytes: int
    sha256: str
    content_base64: str


@dataclass(frozen=True, slots=True)
class PreparedFilesRead:
    document: FilesReadDocument
    wire: bytes


@dataclass(frozen=True, slots=True)
class FilesReadLease:
    context: PanelContext
    credential: PrivateOidcResourceCredential
    expires: datetime


class TrustedFilesContentOwner(Protocol):
    async def read(self, command: PrivateFilesReadCommand) -> VerifiedPrivateFilesRead: ...


class FilesReadAuthority(Protocol):
    async def current(self, project: UUID) -> PanelContext | FilesReadFailure: ...


class FilesReadSessions(Protocol):
    async def credential(
        self, ticket: str, issuer: str, client_id: str, audience: str
    ) -> PrivateOidcResourceCredential | None: ...
    async def session(self, ticket: str) -> PanelOidcSession | None: ...


class FilesReadConnection(Protocol):
    async def is_disconnected(self) -> bool: ...


class FilesReadPreparation(Protocol):
    def prepare(self, path: str, payload: bytes) -> PreparedFilesRead: ...


class ReadFiles:
    def __init__(
        self,
        authority: FilesReadAuthority,
        sessions: FilesReadSessions,
        owner: TrustedFilesContentOwner | None,
        preparation: FilesReadPreparation,
        *,
        audience: str | None,
        client_id: str | None,
    ) -> None:
        self._authority, self._sessions, self._owner = authority, sessions, owner
        self._preparation, self._audience, self._client = preparation, audience, client_id

    async def _lease(
        self, ticket: str, request: FilesReadRequest
    ) -> FilesReadLease | FilesReadFailure:
        context = await self._authority.current(request.project_uuid)
        if isinstance(context, FilesReadFailure):
            return context
        if not project_allows_read(context, request.project_uuid):
            return FilesReadFailure(403, "FILES_READ_PROJECT_DENIED")
        if self._audience is None or self._client is None:
            return FilesReadFailure(503, "FILES_READ_RESOURCE_AUTHORITY_UNAVAILABLE")
        if self._owner is None:
            return FilesReadFailure(503, "FILES_READ_OWNER_UNAVAILABLE")
        try:
            credential = await self._sessions.credential(
                ticket, context.session.issuer, self._client, self._audience
            )
        except (OidcSessionStoreUnavailable, ValueError):
            return FilesReadFailure(503, "FILES_READ_RESOURCE_AUTHORITY_UNAVAILABLE")
        if credential is None or credential.subject != context.session.subject:
            return FilesReadFailure(403, "FILES_READ_RESOURCE_CREDENTIAL_REQUIRED")
        expires = min(context.session.expires_at, context.proof.expires_at, credential.expires_at)
        if expires <= datetime.now(UTC):
            return FilesReadFailure(401, "FILES_READ_PROOF_EXPIRED")
        return FilesReadLease(context, credential, expires)

    async def _read(
        self, command: PrivateFilesReadCommand, connection: FilesReadConnection
    ) -> VerifiedPrivateFilesRead | FilesReadFailure:
        if await connection.is_disconnected():
            return FilesReadFailure(401, "FILES_READ_REQUEST_CANCELLED")
        if self._owner is None:
            return FilesReadFailure(503, "FILES_READ_OWNER_UNAVAILABLE")
        try:
            async with asyncio.timeout(10):
                result = await self._owner.read(command)
        except FilesContentDenied:
            return FilesReadFailure(403, "FILES_READ_DENIED")
        except Exception:
            return FilesReadFailure(503, "FILES_READ_OWNER_UNAVAILABLE")
        if not valid_owner_read(
            result, command, expires=command.proof_expires_at, now=datetime.now(UTC)
        ):
            return FilesReadFailure(503, "FILES_READ_OWNER_INVALID_RESPONSE")
        if await connection.is_disconnected():
            return FilesReadFailure(401, "FILES_READ_REQUEST_CANCELLED")
        return result

    async def _recheck(
        self, ticket: str, lease: FilesReadLease, request: FilesReadRequest, owner_expires: datetime
    ) -> FilesReadFailure | None:
        latest = await self._authority.current(request.project_uuid)
        if isinstance(latest, FilesReadFailure):
            return latest
        if not files_authority_continues(latest, lease.context):
            return FilesReadFailure(403, "FILES_READ_PROJECT_CHANGED")
        if self._audience is None or self._client is None:
            return FilesReadFailure(503, "FILES_READ_RESOURCE_AUTHORITY_UNAVAILABLE")
        try:
            refreshed = await self._sessions.session(ticket)
            again = await self._sessions.credential(
                ticket, lease.context.session.issuer, self._client, self._audience
            )
        except (OidcSessionStoreUnavailable, ValueError):
            return FilesReadFailure(503, "FILES_READ_SESSION_RECHECK_UNAVAILABLE")
        if not files_session_continues(
            refreshed,
            again,
            lease.context,
            latest,
            lease.credential,
            expires=lease.expires,
            owner_expires=owner_expires,
            now=datetime.now(UTC),
        ):
            return FilesReadFailure(401, "FILES_READ_SESSION_EXPIRED_OR_REVOKED")
        return None

    async def execute(
        self, ticket: str, request: FilesReadRequest, connection: FilesReadConnection
    ) -> PreparedFilesRead | FilesReadFailure:
        lease = await self._lease(ticket, request)
        if isinstance(lease, FilesReadFailure):
            return lease
        command = PrivateFilesReadCommand(
            uuid4(),
            lease.context.proof.user_uuid,
            lease.context.session.issuer,
            lease.context.session.subject,
            request.project_uuid,
            request.agent_session_uuid,
            request.expected_grant_revision,
            files_selector(request.project_uuid, request.path),
            request.path,
            request.max_bytes,
            lease.credential.bearer,
            lease.expires,
        )
        result = await self._read(command, connection)
        if isinstance(result, FilesReadFailure):
            return result
        # Base64, digest and full wire encoding must finish BEFORE the last authority/private reads.
        prepared = self._preparation.prepare(request.path, result.payload)
        failure = await self._recheck(ticket, lease, request, result.expires_at)
        return failure if failure is not None else prepared
