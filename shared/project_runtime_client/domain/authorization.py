"""Project identity, authority fences and current capability invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from project_runtime_client.domain._code_error import _CodeError

from .identifiers import valid_uuid
from .revisions import valid_project_revision

ProjectAction = Literal[
    "files.read",
    "files.write",
    "files.manage",
    "terminal.attach",
    "web.internal",
    "web.remote",
    "reverse.import",
    "reverse.read",
    "svc.read",
    "svc.write",
    "infrastructure.read",
    "resources.use",
]


@dataclass(frozen=True, slots=True)
class ProjectOperationScope:
    """Trusted in-process preflight identity, NOT authorization by itself.

    Gateway derives this from a validated, canonical Pydantic request BEFORE
    any A5 signed proof is requested. Backend MUST independently authenticate
    the service+delegated human and consume matching single-use JWT JTIs.
    """

    project_id: UUID
    agent_session_uuid: UUID
    action: ProjectAction
    request_uuid: UUID
    fingerprint: str
    resource_id: UUID | None = None

    def __post_init__(self) -> None:
        if (
            not valid_uuid(self.project_id)
            or not valid_uuid(self.agent_session_uuid)
            or self.agent_session_uuid.version != 4
            or not valid_uuid(self.request_uuid)
            or self.request_uuid.version != 4
            or not valid_project_revision(self.fingerprint)
            or (self.resource_id is not None and not valid_uuid(self.resource_id))
        ):
            raise ProjectAccessDenied("PROJECT_OPERATION_SCOPE_INVALID")


class ProjectAccessDenied(_CodeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectInvocation:
    """Untrusted scope selectors for independently authenticated owner operations.

    Transport credentials stay outside the domain in request-bound ports.
    Constructing this value establishes no caller identity, service identity
    or authorization.
    """

    project_id: UUID
    session_uuid: UUID
    operation_scope: ProjectOperationScope | None = None

    def __post_init__(self) -> None:
        if not valid_uuid(self.project_id):
            raise ProjectAccessDenied("PROJECT_ID_INVALID")
        if not valid_uuid(self.session_uuid) or self.session_uuid.version != 4:
            raise ProjectAccessDenied("SESSION_UUID_INVALID")
        if self.operation_scope is not None and not isinstance(
            self.operation_scope, ProjectOperationScope
        ):
            raise ProjectAccessDenied("PROJECT_OPERATION_SCOPE_INVALID")
        if self.operation_scope is not None and (
            self.operation_scope.project_id != self.project_id
            or self.operation_scope.agent_session_uuid != self.session_uuid
        ):
            raise ProjectAccessDenied("PROJECT_OPERATION_SCOPE_INVALID")


@dataclass(frozen=True, slots=True)
class ProjectOwnerFence:
    """Opaque, owner-issued version triple; NOT a cross-DB SQL transaction.

    Each independently trusted source must recheck Identity activity,
    Control Project/Team membership and Access Session revocation at the
    actual effect boundary. Projections/events are never these proofs.
    """

    identity_version: int
    identity_revocation_epoch: int
    identity_authority_epoch: UUID
    control_state_version: int
    control_revision: str
    control_scope_epoch: int
    control_authority_epoch: UUID
    access_session_version: int
    access_revocation_epoch: int
    access_authority_epoch: UUID

    def valid(self) -> bool:
        return (
            type(self.identity_version) is int
            and self.identity_version >= 1
            and type(self.identity_revocation_epoch) is int
            and self.identity_revocation_epoch >= 0
            and valid_uuid(self.identity_authority_epoch, version=4)
            and type(self.control_state_version) is int
            and self.control_state_version >= 1
            and valid_project_revision(self.control_revision)
            and type(self.control_scope_epoch) is int
            and self.control_scope_epoch >= 0
            and valid_uuid(self.control_authority_epoch, version=4)
            and type(self.access_session_version) is int
            and self.access_session_version >= 1
            and type(self.access_revocation_epoch) is int
            and self.access_revocation_epoch >= 0
            and valid_uuid(self.access_authority_epoch, version=4)
        )


@dataclass(frozen=True, slots=True)
class ProjectPermit:
    """Internal result issued ONLY by an authenticated backend authorization port."""

    project_id: UUID
    actor_id: UUID
    session_uuid: UUID
    action: ProjectAction
    expires_at: datetime
    decision_version: int
    project_access_revision: str | None = None
    project_owner_scope: Literal["team", "project"] | None = None
    project_owner_id: UUID | None = None
    owner_fence: ProjectOwnerFence | None = None

    def require_for(
        self,
        invocation: ProjectInvocation,
        action: ProjectAction,
        *,
        now: datetime,
    ) -> None:
        self._require_subject(invocation, action)
        self._require_fence()
        self._require_owner(invocation.project_id)
        if not isinstance(self.expires_at, datetime):
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_INVALID")
        if self.expires_at.tzinfo is None or self.expires_at <= now:
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_INVALID")

    def _require_subject(self, invocation: ProjectInvocation, action: ProjectAction) -> None:
        if (
            self.project_id != invocation.project_id
            or self.session_uuid != invocation.session_uuid
            or self.action != action
            or not valid_uuid(self.actor_id)
            or type(self.decision_version) is not int
            or self.decision_version < 1
        ):
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_INVALID")

    def _require_fence(self) -> None:
        if not isinstance(self.owner_fence, ProjectOwnerFence):
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_INVALID")
        if (
            not self.owner_fence.valid()
            or self.decision_version != self.owner_fence.access_session_version
            or self.project_access_revision != self.owner_fence.control_revision
            or not valid_project_revision(self.project_access_revision)
        ):
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_INVALID")

    def _require_owner(self, project_uuid: UUID) -> None:
        if (self.project_owner_scope is None) != (self.project_owner_id is None):
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_INVALID")
        if self.project_owner_scope is None:
            return
        if (
            self.project_owner_scope not in {"team", "project"}
            or not valid_uuid(self.project_owner_id)
            or (self.project_owner_scope == "project" and self.project_owner_id != project_uuid)
        ):
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_INVALID")
