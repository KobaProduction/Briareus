"""Single SVC source-selection invariant implementation with local nominal composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from project_runtime_client.domain.authorization import (
    ProjectAccessDenied,
    ProjectInvocation,
    ProjectOperationScope,
    ProjectOwnerFence,
    ProjectPermit,
)
from project_runtime_client.domain.identifiers import valid_uuid
from project_runtime_client.domain.timestamps import aware_timestamp

SVCProvider = Literal["github", "gitlab"]
SVCAction = Literal["svc.read", "svc.write"]


class _PeerFailure:
    __slots__ = ()
    _unavailable: ClassVar[type[ProjectAccessDenied]]


@dataclass(frozen=True, slots=True)
class VerifiedSVCPeer(_PeerFailure):
    """Common peer fields and checks; the composing local class supplies its error type."""

    project_id: UUID
    actor_id: UUID
    session_uuid: UUID
    operation_uuid: UUID
    service_id: UUID
    instance_uuid: UUID
    consumed_jti: UUID
    recipient: Literal["svc"]
    provider: SVCProvider
    action: SVCAction
    original_idempotency_key: str
    source_owner_fence: ProjectOwnerFence
    expires_at: datetime

    def require_for(
        self,
        initial: ProjectPermit,
        scope: ProjectOperationScope,
        *,
        provider: SVCProvider,
        action: SVCAction,
        now: datetime,
    ) -> None:
        self._require_identity(provider, action)
        self._require_binding(initial, scope)
        if (
            not aware_timestamp(self.expires_at)
            or self.expires_at.utcoffset() is None
            or self.expires_at <= now
            or (self.expires_at > initial.expires_at)
        ):
            raise self._unavailable("SVC_VERIFIED_PEER_SCOPE_CHANGED")

    def _require_identity(self, provider: SVCProvider, action: SVCAction) -> None:
        identifiers = (
            self.project_id,
            self.actor_id,
            self.session_uuid,
            self.operation_uuid,
            self.service_id,
            self.instance_uuid,
            self.consumed_jti,
        )
        if (
            not all(valid_uuid(value, version=4) for value in identifiers)
            or self.provider != provider
            or self.action != action
        ):
            raise self._unavailable("SVC_VERIFIED_PEER_SCOPE_CHANGED")
        if self.recipient != "svc":
            raise self._unavailable("SVC_VERIFIED_PEER_SCOPE_CHANGED")

    def _require_binding(self, initial: ProjectPermit, scope: ProjectOperationScope) -> None:
        if (
            self.project_id != initial.project_id
            or self.actor_id != initial.actor_id
            or self.session_uuid != initial.session_uuid
            or (self.operation_uuid != scope.request_uuid)
            or (self.original_idempotency_key != str(scope.request_uuid))
            or (self.source_owner_fence != initial.owner_fence)
        ):
            raise self._unavailable("SVC_VERIFIED_PEER_SCOPE_CHANGED")


@dataclass(frozen=True, slots=True)
class SVCSourceSelection:
    """Privately approved source label; NEVER a tool call or access token."""

    provider: SVCProvider
    module_name: str
    handler_name: Literal["mcp"]
    operation_uuid: UUID
    recipient_service_id: UUID
    recipient_instance_uuid: UUID


@dataclass(frozen=True, slots=True)
class SourceSelectionRules[PeerT: VerifiedSVCPeer]:
    provider_available: Callable[[SVCProvider], bool]
    unavailable: type[ProjectAccessDenied]

    def require_original_scope(
        self,
        invocation: ProjectInvocation,
        *,
        provider: SVCProvider,
        action: SVCAction,
        service_source_available: bool,
    ) -> ProjectOperationScope:
        if not self.provider_available(provider) or action not in {"svc.read", "svc.write"}:
            raise self.unavailable("SVC_PROVIDER_OR_ACTION_NOT_ACCEPTED")
        scope = invocation.operation_scope
        if (
            not service_source_available
            or scope is None
            or scope.action != action
            or (scope.project_id != invocation.project_id)
            or (scope.agent_session_uuid != invocation.session_uuid)
            or (not valid_uuid(scope.request_uuid, version=4))
        ):
            raise self.unavailable("SVC_SIGNED_C2_OR_ORIGINAL_SCOPE_REQUIRED")
        return scope

    def require_initial_grant(self, permit: ProjectPermit, *, now: datetime) -> None:
        if (
            permit.owner_fence is None
            or not aware_timestamp(permit.expires_at)
            or permit.expires_at.utcoffset() is None
            or (permit.expires_at <= now)
        ):
            raise self.unavailable("SVC_THREE_OWNER_FENCE_REQUIRED")

    def require_refreshed_grant(
        self,
        initial: ProjectPermit,
        current: ProjectPermit,
        peer: PeerT,
        *,
        grant_observed_at: datetime,
        peer_observed_at: datetime,
    ) -> None:
        if (
            current.project_id != initial.project_id
            or current.actor_id != initial.actor_id
            or current.session_uuid != initial.session_uuid
            or (current.project_owner_id != initial.project_owner_id)
            or (current.project_owner_scope != initial.project_owner_scope)
            or (current.project_access_revision != initial.project_access_revision)
            or (current.owner_fence != initial.owner_fence)
            or (current.decision_version != initial.decision_version)
        ):
            raise self.unavailable("SVC_CURRENT_GRANT_REVOKED")
        if (
            not aware_timestamp(current.expires_at)
            or current.expires_at.utcoffset() is None
            or current.expires_at <= grant_observed_at
            or (peer.expires_at > current.expires_at)
            or (peer.expires_at <= peer_observed_at)
        ):
            raise self.unavailable("SVC_CURRENT_GRANT_REVOKED")
