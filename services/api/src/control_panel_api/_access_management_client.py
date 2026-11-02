"""Bounded private Access owner transport for source-verified approval lists.

No Access SQL, Provider Admin API key, or self-issued User bearer enters the
Control Panel BFF. The transport and short-lived User delegation are supplied
only by an independently authenticated service peer. Without a real
Authorization command port, approval writes deliberately fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from control_panel_api.application.approval_scopes import ScopedEffectPayload
from control_panel_api.domain.access_receipts import ApprovalReceiptFacts
from control_panel_api.domain.approval_policy import ApprovalLifecycle, boolean, uuid4
from control_panel_api.domain.private_authority import current_deadline, exact_text

from .application.approval_contracts import (
    ApprovalSnapshot,
    CurrentSessionSnapshot,
    GrantSnapshot,
    OwnerManagementConflict,
    OwnerManagementDenied,
    OwnerManagementNotFound,
    OwnerManagementUnavailable,
)

_LIST = "http://briareus-authorization:8000/internal/v1/authorization/approvals/list"
_SESSIONS_LIST = "http://briareus-authorization:8000/internal/v1/authorization/sessions/list"
_SESSIONS_GET = "http://briareus-authorization:8000/internal/v1/authorization/sessions/get"
_MAX_BODY = 48_000


@dataclass(frozen=True, slots=True)
class VerifiedAccessTransport:
    client: httpx.AsyncClient
    mode: Literal["mtls", "unix-peer"]
    audience: Literal["briareus:access"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedAccessActorDelegation:
    issuer: Literal["rauthy"]
    actor_uuid: UUID
    project_uuid: UUID
    may_approve: bool
    bearer: SecretStr
    audience: Literal["briareus:access"]
    expires_at: datetime


class TrustedAccessPeerPort(Protocol):
    async def current_transport(self) -> VerifiedAccessTransport:
        """Authenticated private service peer; never a raw Docker link."""
        ...

    async def signed_actor_delegation(
        self, *, actor_uuid: UUID, project_uuid: UUID
    ) -> VerifiedAccessActorDelegation:
        """Fresh user+Project proof issued by independently verified owner."""
        ...


class _ApprovalOwnerItem(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    created_at: datetime | None = None
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    requested_by_user_uuid: UUID
    status: Literal["pending", "approved", "rejected"]
    version: int = Field(strict=True, ge=1)
    requested_operations: tuple[str, ...] = Field(max_length=32)
    requested_resources: tuple[ScopedEffectPayload, ...] = Field(max_length=32)
    requested_expires_at: datetime
    resolved_by_user_uuid: UUID | None = None
    issued_session_uuid: UUID | None = None
    allowed_actions: tuple[Literal["approve", "deny"], ...] = ()


class _ApprovalOwnerList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[_ApprovalOwnerItem, ...] = Field(max_length=50)


class _SessionOwnerItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_uuid: UUID
    project_uuid: UUID
    label: str | None = Field(default=None, max_length=128)
    created_at: datetime | None = None
    created_by_user_uuid: UUID
    revision: int = Field(strict=True, ge=1)
    status: Literal["active", "revoked", "expired"]
    is_elevated: bool = Field(strict=True)
    elevation_policy: Literal["fixed", "requestable"]
    hard_expires_at: datetime
    operations: tuple[str, ...] = Field(min_length=1, max_length=32)
    resources: tuple[ScopedEffectPayload, ...] = Field(max_length=32)
    allowed_actions: tuple[Literal["revoke"], ...] = Field(default=(), max_length=1)


class _SessionOwnerList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[_SessionOwnerItem, ...] = Field(max_length=50)


class _SessionOwnerGet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item: _SessionOwnerItem


class _SessionOwnerMissing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    detail: Literal["AgentSession not found"]


class AccessReadBody(NamedTuple):
    raw: bytes
    delegate: VerifiedAccessActorDelegation


class AttestedAccessRead(NamedTuple):
    transport: VerifiedAccessTransport
    delegate: VerifiedAccessActorDelegation
    bearer: str


def attested_reader(
    transport: object, delegate: object, actor: UUID, project: UUID
) -> AttestedAccessRead:
    now = datetime.now(UTC)
    if (
        not isinstance(transport, VerifiedAccessTransport)
        or transport.mode not in {"mtls", "unix-peer"}
        or not exact_text(transport.audience, "briareus:access")
        or not current_deadline(transport.expires_at, now=now, upper=now + timedelta(seconds=30))
        or not isinstance(delegate, VerifiedAccessActorDelegation)
        or not exact_text(delegate.issuer, "rauthy")
        or delegate.actor_uuid != actor
        or delegate.project_uuid != project
        or not boolean(delegate.may_approve)
        or not exact_text(delegate.audience, "briareus:access")
        or not current_deadline(delegate.expires_at, now=now, upper=transport.expires_at)
    ):
        raise OwnerManagementUnavailable("untrusted Access peer User grant")
    bearer = delegate.bearer.get_secret_value()
    if (
        not bearer
        or not bearer.isascii()
        or len(bearer) > 8192
        or any(character.isspace() for character in bearer)
    ):
        raise OwnerManagementUnavailable("invalid signed private Access bearer")
    return AttestedAccessRead(transport, delegate, bearer)


class PrivateAccessManagementClient:
    """Read owner-confirmed approval state. Writes need a separately signed port."""

    def __init__(self, *, trusted_peer: TrustedAccessPeerPort) -> None:
        if trusted_peer is None:
            raise ValueError("access service peer required")
        self._peer = trusted_peer

    async def _attested_reader(self, actor: UUID, project: UUID) -> AttestedAccessRead:
        try:
            transport = await self._peer.current_transport()
            delegate = await self._peer.signed_actor_delegation(
                actor_uuid=actor, project_uuid=project
            )
        except Exception:
            raise OwnerManagementUnavailable("Access peer attestation unavailable") from None
        return attested_reader(transport, delegate, actor, project)

    async def _read_private(
        self,
        *,
        actor: UUID,
        project: UUID,
        limit: int,
        destination: str,
        session: UUID | None = None,
    ) -> AccessReadBody:
        if destination not in {_LIST, _SESSIONS_LIST, _SESSIONS_GET}:
            raise ValueError("private Access owner destination not allowlisted")
        if (
            not uuid4(actor)
            or not uuid4(project)
            or type(limit) is not int
            or not 1 <= limit <= 50
            or (destination == _SESSIONS_GET) != (session is not None)
            or (session is not None and (not uuid4(session) or limit != 1))
        ):
            raise OwnerManagementDenied("invalid scoped approval selectors")
        transport, delegate, bearer = await self._attested_reader(actor, project)
        return await self._read_response(
            transport,
            delegate,
            bearer,
            project=project,
            session=session,
            destination=destination,
            limit=limit,
        )

    async def _read_response(
        self,
        transport: VerifiedAccessTransport,
        delegate: VerifiedAccessActorDelegation,
        bearer: str,
        *,
        project: UUID,
        session: UUID | None,
        destination: str,
        limit: int,
    ) -> AccessReadBody:
        try:
            async with transport.client.stream(
                "POST",
                destination,
                headers={
                    "Authorization": "Bearer " + bearer,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=(
                    {"project_uuid": str(project), "session_uuid": str(session), "limit": 1}
                    if session is not None
                    else {"project_uuid": str(project), "limit": limit}
                ),
                follow_redirects=False,
            ) as response:
                if response.status_code in {401, 403}:
                    raise OwnerManagementDenied("private Access denied")
                if response.status_code == 409:
                    raise OwnerManagementConflict("owner list changed")
                is_missing = response.status_code == 404 and destination == _SESSIONS_GET
                if response.status_code != 200 and not is_missing:
                    raise OwnerManagementUnavailable("private Access unavailable")
                if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise OwnerManagementUnavailable("invalid Access response type")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > _MAX_BODY:
                        raise OwnerManagementUnavailable("Access response too large")
                    raw.extend(chunk)
        except (httpx.HTTPError, TimeoutError):
            raise OwnerManagementUnavailable("Access transport unavailable") from None
        if delegate.expires_at <= datetime.now(UTC):
            raise OwnerManagementUnavailable("Access authority expired during read")
        if is_missing:
            # An unmounted route/proxy 404 is NOT proof of an absent session.
            # Only the authenticated owner's exact missing DTO may map to 404.
            try:
                _SessionOwnerMissing.model_validate_json(raw)
            except (ValidationError, ValueError):
                raise OwnerManagementUnavailable("Access detail route unavailable") from None
            raise OwnerManagementNotFound("AgentSession not found")
        return AccessReadBody(bytes(raw), delegate)

    async def list_approvals(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[ApprovalSnapshot, ...]:
        raw, delegate = await self._read_private(
            actor=actor, project=project, limit=limit, destination=_LIST
        )
        try:
            owner_list = _ApprovalOwnerList.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("untrusted Access owner response") from None
        now = datetime.now(UTC)
        if delegate.expires_at <= now:
            raise OwnerManagementUnavailable("Access authority expired during read")
        if len(owner_list.items) > limit:
            raise OwnerManagementUnavailable("Access owner exceeded requested approval limit")
        result: list[ApprovalSnapshot] = []
        seen: set[UUID] = set()
        for item in owner_list.items:
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
            if item.id in seen or not facts.visible(
                project=project,
                actor=actor,
                approver=delegate.may_approve,
                allowed_actions=item.allowed_actions,
                now=now,
            ):
                raise OwnerManagementUnavailable("Access scope mismatch")
            seen.add(item.id)
            result.append(
                ApprovalSnapshot(
                    approval_uuid=item.id,
                    project_uuid=item.project_uuid,
                    agent_session_uuid=item.agent_session_uuid,
                    requested_by_user_uuid=item.requested_by_user_uuid,
                    status=item.status,
                    version=item.version,
                    requested_operations=item.requested_operations,
                    requested_resources=tuple(
                        effect.scope() for effect in item.requested_resources
                    ),
                    requested_expires_at=item.requested_expires_at,
                    resolved_by_user_uuid=item.resolved_by_user_uuid,
                    issued_session_uuid=item.issued_session_uuid,
                    label=item.label,
                    created_at=item.created_at,
                )
            )
        return tuple(result)

    @staticmethod
    def _decode_sessions(
        *,
        items: tuple[_SessionOwnerItem, ...],
        delegate: VerifiedAccessActorDelegation,
        actor: UUID,
        project: UUID,
    ) -> tuple[CurrentSessionSnapshot, ...]:
        now = datetime.now(UTC)
        if delegate.expires_at <= now:
            raise OwnerManagementUnavailable("Access actor expired while decoding sessions")
        result: list[CurrentSessionSnapshot] = []
        seen: set[UUID] = set()
        for item in items:
            if (
                item.project_uuid != project
                or item.session_uuid.version != 4
                or item.session_uuid in seen
                or item.created_by_user_uuid.version != 4
                or (not delegate.may_approve and item.created_by_user_uuid != actor)
                or item.hard_expires_at.tzinfo is None
                or (item.status == "active" and item.hard_expires_at <= now)
                or (item.status == "expired" and item.hard_expires_at > now)
                or (
                    item.allowed_actions
                    and (
                        not delegate.may_approve
                        or item.status != "active"
                        or item.hard_expires_at <= now
                    )
                )
            ):
                raise OwnerManagementUnavailable("Access session inventory scope mismatch")
            seen.add(item.session_uuid)
            result.append(
                CurrentSessionSnapshot(
                    session_uuid=item.session_uuid,
                    project_uuid=item.project_uuid,
                    created_by_user_uuid=item.created_by_user_uuid,
                    revision=item.revision,
                    status=item.status,
                    is_elevated=item.is_elevated,
                    elevation_policy=item.elevation_policy,
                    hard_expires_at=item.hard_expires_at,
                    operations=item.operations,
                    resources=tuple(effect.scope() for effect in item.resources),
                    allowed_actions=item.allowed_actions,
                    label=item.label,
                    created_at=item.created_at,
                )
            )
        if delegate.expires_at <= datetime.now(UTC):
            raise OwnerManagementUnavailable("Access actor expired during session validation")
        return tuple(result)

    async def list_sessions(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[CurrentSessionSnapshot, ...]:
        raw, delegate = await self._read_private(
            actor=actor, project=project, limit=limit, destination=_SESSIONS_LIST
        )
        try:
            owner_list = _SessionOwnerList.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("Access session inventory malformed") from None
        if len(owner_list.items) > limit:
            raise OwnerManagementUnavailable("Access owner exceeded requested session limit")
        return self._decode_sessions(
            items=owner_list.items, delegate=delegate, actor=actor, project=project
        )

    async def get_session(
        self, *, actor: UUID, project: UUID, session: UUID
    ) -> CurrentSessionSnapshot:
        raw, delegate = await self._read_private(
            actor=actor,
            project=project,
            session=session,
            limit=1,
            destination=_SESSIONS_GET,
        )
        try:
            owner_get = _SessionOwnerGet.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise OwnerManagementUnavailable("Access session detail malformed") from None
        if owner_get.item.session_uuid != session:
            raise OwnerManagementUnavailable("Access session selector mismatch")
        decoded = self._decode_sessions(
            items=(owner_get.item,), delegate=delegate, actor=actor, project=project
        )
        if delegate.expires_at <= datetime.now(UTC) or len(decoded) != 1:
            raise OwnerManagementUnavailable("Access session detail proof expired")
        return decoded[0]

    async def request_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        operations: tuple[str, ...],
        resources: tuple[ScopedEffectPayload, ...],
        seconds: int,
        expected_grant_revision: int,
        operation: UUID,
    ) -> ApprovalSnapshot:
        _ = (
            actor,
            project,
            session,
            operations,
            resources,
            seconds,
            expected_grant_revision,
            operation,
        )
        raise OwnerManagementUnavailable("signed Access command port unavailable")

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
        _ = (actor, project, approval, expected_version, approve, allowed_operations, operation)
        raise OwnerManagementUnavailable("signed Access command port unavailable")

    async def revoke_session(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        expected_revision: int,
        operation: UUID,
    ) -> GrantSnapshot:
        _ = (actor, project, session, expected_revision, operation)
        raise OwnerManagementUnavailable("signed Access command port unavailable")
