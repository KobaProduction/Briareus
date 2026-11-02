"""Authenticated, exact-body signed Access management command transport.

The browser owns neither service credential nor User identity. A real private
peer signs a short-lived delegated Rauthy/Platform actor AND the exact command
hash. The destination is fixed; the Authorization service independently checks
the signature, peer and current owner SQL/idempotent state before any mutation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, ValidationError

from control_panel_api.application.approval_scopes import ScopedEffectPayload
from control_panel_api.domain.access_receipts import ApprovalReceiptFacts
from control_panel_api.domain.approval_policy import ApprovalLifecycle, EffectScope, uuid4
from control_panel_api.domain.private_authority import current_deadline, exact_text
from control_panel_api.infrastructure.json_fields import validate_unique_fields
from runtime_peer.access_management_wire import (
    AccessWriteInput,
    OpenSessionInput,
    RequestElevationInput,
    ResolveElevationInput,
    RevokeSessionInput,
)

from ._access_management_client import (
    TrustedAccessPeerPort,
    VerifiedAccessTransport,
)
from .application.approval_contracts import (
    ApprovalSnapshot,
    CurrentSessionSnapshot,
    GrantSnapshot,
    OpenSessionSnapshot,
    OwnerManagementConflict,
    OwnerManagementDenied,
    OwnerManagementInvalidInput,
    OwnerManagementUnavailable,
)

_ACTIONS: dict[str, str] = {
    "open": "session.open",
    "request": "session.request_elevation",
    "resolve": "session.resolve_elevation",
    "revoke": "session.revoke",
}
_ROUTES: dict[str, str] = {
    "open": "http://briareus-authorization:8000/internal/v1/authorization/sessions/open",
    "request": "http://briareus-authorization:8000/internal/v1/authorization/approvals/request",
    "resolve": "http://briareus-authorization:8000/internal/v1/authorization/approvals/resolve",
    "revoke": "http://briareus-authorization:8000/internal/v1/authorization/sessions/revoke",
}
_MAX_BYTES = 48_000
_OWNER_DEADLINE_SECONDS = 12
_UUID_SELECTOR: TypeAdapter[UUID] = TypeAdapter(UUID)


def _strict_receipt[Receipt: BaseModel](raw: bytes, model: type[Receipt]) -> Receipt:
    try:
        validate_unique_fields(raw)
        value: object = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise OwnerManagementUnavailable("ambiguous private Access owner receipt") from None
    return model.model_validate(value)


@contextmanager
def _command_validation() -> Iterator[None]:
    try:
        yield
    except (ValueError, TypeError):
        raise OwnerManagementInvalidInput("private Access command scope invalid") from None


@dataclass(frozen=True, slots=True)
class VerifiedAccessWriteDelegation:
    """Signed delegation, not a browser claim or a random authorization header."""

    issuer: Literal["rauthy"]
    actor_uuid: UUID
    project_uuid: UUID
    operation_uuid: UUID
    action: Literal[
        "session.open", "session.request_elevation", "session.resolve_elevation", "session.revoke"
    ]
    body_sha256: str
    bearer: SecretStr
    audience: Literal["briareus:access"]
    expires_at: datetime


class TrustedAccessWritePeerPort(TrustedAccessPeerPort, Protocol):
    async def signed_command_delegation(
        self,
        *,
        actor_uuid: UUID,
        project_uuid: UUID,
        operation_uuid: UUID,
        action: str,
        body_sha256: str,
    ) -> VerifiedAccessWriteDelegation:
        """Independently verify live Rauthy User/Project then sign exact command."""
        ...


class _OpenReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_uuid: UUID
    project_uuid: UUID
    revision: int = Field(strict=True, ge=1)
    status: Literal["active"]
    is_elevated: Literal[False]
    elevation_policy: Literal["fixed", "requestable"]
    hard_expires_at: datetime
    operations: tuple[str, ...]
    resources: tuple[ScopedEffectPayload, ...]


class _ApprovalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    requested_by_user_uuid: UUID
    status: Literal["pending", "approved", "rejected"]
    version: int = Field(strict=True, ge=1)
    requested_operations: tuple[str, ...] = Field(min_length=1, max_length=32)
    requested_resources: tuple[ScopedEffectPayload, ...] = Field(max_length=32)
    requested_expires_at: datetime
    resolved_by_user_uuid: UUID | None = None
    issued_session_uuid: UUID | None = None


class _RevokeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_uuid: UUID
    project_uuid: UUID
    status: Literal["revoked"]
    revision: int = Field(strict=True, ge=2)


class AttestedAccessWrite(NamedTuple):
    transport: VerifiedAccessTransport
    delegated: VerifiedAccessWriteDelegation
    bearer: str


def attested_writer(
    transport: object,
    delegated: object,
    *,
    actor: UUID,
    project: UUID,
    operation: UUID,
    action: str,
    body_hash: str,
) -> AttestedAccessWrite:
    now = datetime.now(UTC)
    if (
        not isinstance(transport, VerifiedAccessTransport)
        or transport.mode not in {"mtls", "unix-peer"}
        or not exact_text(transport.audience, "briareus:access")
        or not current_deadline(transport.expires_at, now=now, upper=now + timedelta(seconds=30))
        or not isinstance(delegated, VerifiedAccessWriteDelegation)
        or not exact_text(delegated.issuer, "rauthy")
        or delegated.actor_uuid != actor
        or delegated.project_uuid != project
        or delegated.operation_uuid != operation
        or delegated.action != _ACTIONS[action]
        or delegated.body_sha256 != body_hash
        or not exact_text(delegated.audience, "briareus:access")
        or not current_deadline(delegated.expires_at, now=now, upper=transport.expires_at)
    ):
        raise OwnerManagementUnavailable("private Access command not attested")
    bearer = delegated.bearer.get_secret_value()
    if (
        not 40 <= len(bearer) <= 8192
        or not bearer.isascii()
        or any(char.isspace() for char in bearer)
    ):
        raise OwnerManagementUnavailable("private signed Access bearer invalid")

    return AttestedAccessWrite(transport, delegated, bearer)


class PrivateAccessManagementWriter:
    def __init__(self, *, trusted_peer: TrustedAccessWritePeerPort) -> None:
        if trusted_peer is None:
            raise ValueError("independent signed Access write peer required")
        self._peer = trusted_peer

    async def _attested_writer(
        self,
        *,
        actor: UUID,
        project: UUID,
        operation: UUID,
        action: str,
        body_hash: str,
        deadline: float,
    ) -> AttestedAccessWrite:
        try:
            async with asyncio.timeout_at(deadline):
                transport = await self._peer.current_transport()
                delegated = await self._peer.signed_command_delegation(
                    actor_uuid=actor,
                    project_uuid=project,
                    operation_uuid=operation,
                    action=_ACTIONS[action],
                    body_sha256=body_hash,
                )
        except Exception:
            raise OwnerManagementUnavailable("signed owner transport unavailable") from None
        return attested_writer(
            transport,
            delegated,
            actor=actor,
            project=project,
            operation=operation,
            action=action,
            body_hash=body_hash,
        )

    async def _write(
        self,
        *,
        action: Literal["open", "request", "resolve", "revoke"],
        actor: UUID,
        project: UUID,
        operation: UUID,
        fields: AccessWriteInput,
        expected_code: int,
    ) -> bytes:
        if (
            not uuid4(actor)
            or not uuid4(project)
            or not uuid4(operation)
            or fields.operation_uuid != operation
        ):
            raise OwnerManagementDenied("invalid authoritative Access selector")
        command = {
            "project_uuid": str(project),
            **fields.model_dump(mode="json"),
        }
        # Stable canonical bytes avoid signature/authorization ambiguity.
        try:
            serialized = json.dumps(
                command,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        except (TypeError, ValueError, UnicodeEncodeError):
            raise OwnerManagementDenied("invalid Access owner command") from None
        if not 1 <= len(serialized) <= 32_768:
            raise OwnerManagementDenied("Access command out of bounds")
        body_hash = hashlib.sha256(serialized).hexdigest()
        deadline = asyncio.get_running_loop().time() + _OWNER_DEADLINE_SECONDS
        transport, delegated, bearer = await self._attested_writer(
            actor=actor,
            project=project,
            operation=operation,
            action=action,
            body_hash=body_hash,
            deadline=deadline,
        )

        try:
            async with (
                asyncio.timeout_at(deadline),
                transport.client.stream(
                    "POST",
                    _ROUTES[action],
                    content=serialized,
                    headers={
                        "Authorization": "Bearer " + bearer,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Operation-UUID": str(operation),
                        "Idempotency-Key": str(operation),
                    },
                    follow_redirects=False,
                ) as response,
            ):
                if response.status_code in {401, 403}:
                    raise OwnerManagementDenied("Authorization owner denied Access command")
                if response.status_code == 409:
                    raise OwnerManagementConflict("current grant revision conflict")
                if response.status_code == 422:
                    raise OwnerManagementInvalidInput("private Access command scope invalid")
                if response.status_code != expected_code:
                    raise OwnerManagementUnavailable("Authorization owner did not commit command")
                if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise OwnerManagementUnavailable("invalid owner response MIME")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > _MAX_BYTES:
                        raise OwnerManagementUnavailable("owner response exceeds limit")
                    raw.extend(chunk)
        except (httpx.HTTPError, TimeoutError):
            raise OwnerManagementUnavailable("Access write transport unavailable") from None
        if delegated.expires_at <= datetime.now(UTC):
            raise OwnerManagementUnavailable("Access owner delegation expired during write")
        return bytes(raw)

    @staticmethod
    def _approval(
        raw: bytes,
        *,
        project: UUID,
        actor: UUID,
        state: str,
        expected_approval: UUID | None = None,
    ) -> ApprovalSnapshot:
        try:
            item = _strict_receipt(raw, _ApprovalReceipt)
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("Authorization approval response invalid") from None
        facts = ApprovalReceiptFacts(
            item.id,
            item.project_uuid,
            ApprovalLifecycle(
                item.status,
                item.requested_by_user_uuid,
                item.agent_session_uuid,
                item.resolved_by_user_uuid,
                item.issued_session_uuid,
            ),
            item.version,
            item.requested_expires_at,
            item.requested_operations,
        )
        if not facts.matches(project=project, actor=actor, state=state, expected=expected_approval):
            raise OwnerManagementUnavailable("Authorization approved a foreign scope")
        try:
            effects = tuple(effect.scope() for effect in item.requested_resources)
        except ValueError:
            raise OwnerManagementUnavailable(
                "Authorization approval resource scope invalid"
            ) from None
        if len(set(effects)) != len(effects) or any(
            effect.action not in item.requested_operations for effect in effects
        ):
            raise OwnerManagementUnavailable("Authorization approval resource scope mismatch")
        return ApprovalSnapshot(
            approval_uuid=item.id,
            project_uuid=item.project_uuid,
            agent_session_uuid=item.agent_session_uuid,
            requested_by_user_uuid=item.requested_by_user_uuid,
            status=item.status,
            version=item.version,
            requested_operations=item.requested_operations,
            requested_resources=effects,
            requested_expires_at=item.requested_expires_at,
            resolved_by_user_uuid=item.resolved_by_user_uuid,
            issued_session_uuid=item.issued_session_uuid,
        )

    async def open_normal(
        self,
        *,
        actor: UUID,
        project: UUID,
        elevation_policy: Literal["fixed", "requestable"],
        label: str | None,
        operation: UUID,
    ) -> OpenSessionSnapshot:
        with _command_validation():
            command = OpenSessionInput(
                operation_uuid=operation,
                elevation_policy=elevation_policy,
                label=label,
            )
        raw = await self._write(
            action="open",
            actor=actor,
            project=project,
            operation=operation,
            fields=command,
            expected_code=201,
        )
        try:
            receipt = _strict_receipt(raw, _OpenReceipt)
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("Access owner opening receipt invalid") from None
        now = datetime.now(UTC)
        if (
            receipt.session_uuid.version != 4
            or receipt.project_uuid != project
            or receipt.revision != 1
            or receipt.elevation_policy != elevation_policy
            or receipt.hard_expires_at.tzinfo is None
            or not now < receipt.hard_expires_at <= now + timedelta(hours=24)
            or receipt.operations != ("files.read", "project.metadata.read")
            or receipt.resources
        ):
            raise OwnerManagementUnavailable("Access owner opened unauthorized session")
        return OpenSessionSnapshot(
            session_uuid=receipt.session_uuid,
            project_uuid=project,
            revision=receipt.revision,
            status="active",
            is_elevated=False,
            elevation_policy=receipt.elevation_policy,
            hard_expires_at=receipt.hard_expires_at,
            operations=receipt.operations,
            resources=tuple(effect.scope() for effect in receipt.resources),
        )

    async def request_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        operations: tuple[str, ...],
        resources: tuple[EffectScope, ...],
        seconds: int,
        expected_grant_revision: int,
        operation: UUID,
    ) -> ApprovalSnapshot:
        session_text = str(session)
        operation_values = tuple(operations)
        scopes = tuple(ScopedEffectPayload.from_scope(effect) for effect in resources)
        with _command_validation():
            command = RequestElevationInput(
                operation_uuid=operation,
                agent_session_uuid=_UUID_SELECTOR.validate_python(session_text),
                operations=operation_values,
                resources=scopes,
                seconds=seconds,
                expected_grant_revision=expected_grant_revision,
            )
        raw = await self._write(
            action="request",
            actor=actor,
            project=project,
            operation=operation,
            fields=command,
            expected_code=202,
        )
        result = self._approval(raw, project=project, actor=actor, state="pending")
        try:
            expected_effects = resources
            received_effects = result.requested_resources
        except ValueError:
            raise OwnerManagementUnavailable("Access request resource scope invalid") from None
        if (
            result.agent_session_uuid != session
            or result.approval_uuid != operation
            or set(result.requested_operations) != set(operations)
            or len(result.requested_operations) != len(operations)
            or len(received_effects) != len(expected_effects)
            or set(received_effects) != set(expected_effects)
        ):
            raise OwnerManagementUnavailable("Access owner request selector mismatch")
        return result

    async def resolve_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        approval: UUID,
        expected_version: int,
        approve: bool,
        allowed_operations: tuple[str, ...] | None,
        operation: UUID,
    ) -> ApprovalSnapshot:
        approval_text = str(approval)
        allowed = tuple(allowed_operations) if allowed_operations is not None else None
        with _command_validation():
            command = ResolveElevationInput(
                operation_uuid=operation,
                approval_uuid=_UUID_SELECTOR.validate_python(approval_text),
                expected_approval_version=expected_version,
                approve=approve,
                allowed_operations=allowed,
            )
        raw = await self._write(
            action="resolve",
            actor=actor,
            project=project,
            operation=operation,
            fields=command,
            expected_code=200,
        )
        result = self._approval(
            raw,
            project=project,
            actor=actor,
            state="approved" if approve else "rejected",
            expected_approval=approval,
        )
        if result.version != expected_version + 1:
            raise OwnerManagementUnavailable("Authorization approval revision mismatch")
        if allowed_operations is not None and not set(allowed_operations) <= set(
            result.requested_operations
        ):
            raise OwnerManagementUnavailable("Authorization approval expanded operation set")
        return result

    async def revoke_session(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        expected_revision: int,
        operation: UUID,
    ) -> GrantSnapshot:
        session_text = str(session)
        with _command_validation():
            command = RevokeSessionInput(
                operation_uuid=operation,
                agent_session_uuid=_UUID_SELECTOR.validate_python(session_text),
                expected_grant_revision=expected_revision,
            )
        raw = await self._write(
            action="revoke",
            actor=actor,
            project=project,
            operation=operation,
            fields=command,
            expected_code=200,
        )
        try:
            item = _strict_receipt(raw, _RevokeReceipt)
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("Authorization revoke receipt invalid") from None
        if (
            item.project_uuid != project
            or item.session_uuid != session
            or item.revision != expected_revision + 1
            or item.session_uuid.version != 4
        ):
            raise OwnerManagementUnavailable("Authorization revoke scope mismatch")
        return GrantSnapshot(
            session_uuid=item.session_uuid,
            project_uuid=project,
            status="revoked",
            revision=item.revision,
        )


class PrivateAccessManagementBundle:
    """One injected verified peer for read AND signed write owner commands.

    Control Panel BFF accepts this as its ApprovalManagementPort. The same
    trusted factory must authenticate both user and service transport
    independently; no service transport is constructed from HTTP input.
    """

    def __init__(self, *, trusted_peer: TrustedAccessWritePeerPort) -> None:
        from ._access_management_client import PrivateAccessManagementClient

        if trusted_peer is None:
            raise ValueError("trusted read and write Access peer required")
        self._read = PrivateAccessManagementClient(trusted_peer=trusted_peer)
        self._write = PrivateAccessManagementWriter(trusted_peer=trusted_peer)

    async def list_approvals(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[ApprovalSnapshot, ...]:
        return await self._read.list_approvals(actor=actor, project=project, limit=limit)

    async def open_normal(
        self,
        *,
        actor: UUID,
        project: UUID,
        elevation_policy: Literal["fixed", "requestable"],
        label: str | None,
        operation: UUID,
    ) -> OpenSessionSnapshot:
        return await self._write.open_normal(
            actor=actor,
            project=project,
            elevation_policy=elevation_policy,
            label=label,
            operation=operation,
        )

    async def list_sessions(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[CurrentSessionSnapshot, ...]:
        return await self._read.list_sessions(actor=actor, project=project, limit=limit)

    async def get_session(
        self, *, actor: UUID, project: UUID, session: UUID
    ) -> CurrentSessionSnapshot:
        return await self._read.get_session(actor=actor, project=project, session=session)

    async def request_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        operations: tuple[str, ...],
        resources: tuple[EffectScope, ...],
        seconds: int,
        expected_grant_revision: int,
        operation: UUID,
    ) -> ApprovalSnapshot:
        return await self._write.request_elevation(
            actor=actor,
            project=project,
            session=session,
            operations=operations,
            resources=resources,
            seconds=seconds,
            expected_grant_revision=expected_grant_revision,
            operation=operation,
        )

    async def resolve_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        approval: UUID,
        expected_version: int,
        approve: bool,
        allowed_operations: tuple[str, ...] | None,
        operation: UUID,
    ) -> ApprovalSnapshot:
        return await self._write.resolve_elevation(
            actor=actor,
            project=project,
            approval=approval,
            expected_version=expected_version,
            approve=approve,
            allowed_operations=allowed_operations,
            operation=operation,
        )

    async def revoke_session(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        expected_revision: int,
        operation: UUID,
    ) -> GrantSnapshot:
        return await self._write.revoke_session(
            actor=actor,
            project=project,
            session=session,
            expected_revision=expected_revision,
            operation=operation,
        )
