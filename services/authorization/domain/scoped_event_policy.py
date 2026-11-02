"""Public scoped-event metadata and security fanout provenance policies."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

PUBLIC_DETAIL_KEYS = frozenset(
    {
        "owner_scope",
        "owner_id",
        "team_id",
        "new_owner_id",
        "new_owner_user_id",
        "new_owner_team_id",
        "old_owner_user_id",
        "old_team_id",
        "resource_id",
        "resource_version",
        "owner_resource_revision",
        "quota_revision",
        "reservation_revision",
        "runtime_revision",
        "job_version",
        "job_status",
        "native_import_version",
        "native_project_id",
        "source_file_version",
        "source_file_object_id",
        "session_version",
        "approved",
        "enabled",
        "artifact_confirmed",
        "reconciliation_required",
        "cleanup_required",
        "over_limit",
    }
)
SECURITY_CHANGES = frozenset(
    {
        "identity.suspended",
        "identity.deleted",
        "identity.role_changed",
        "identity.password_changed",
        "identity.password_reset",
        "identity.browser_telemetry_consent_changed",
        "team.member_removed",
        "team.member_added",
        "team.owner_transferred",
        "project.transferred_to_team",
        "project.withdrawn_to_personal",
        "project.admin_reassigned",
        "session.revoked",
        "resource.integration.rotated",
        "resource.integration.revoked",
        "resource.variable.rotated",
        "resource.variable.revoked",
        "runtime.session_revoked",
        "runtime.session_expired",
    }
)
KINDS = frozenset({"project", "team", "user"})
_IDENTITY_EVENTS = frozenset(
    {
        "identity.suspended",
        "identity.restored",
        "identity.deleted",
        "identity.role_changed",
        "identity.password_changed",
        "identity.password_reset",
        "identity.browser_telemetry_consent_changed",
    }
)


@dataclass(frozen=True, slots=True)
class PublicScopePayload:
    owner_scope: str | None = None
    owner_id: UUID | None = None
    team_id: UUID | None = None
    new_owner_id: UUID | None = None
    new_owner_user_id: UUID | None = None
    new_owner_team_id: UUID | None = None
    old_owner_user_id: UUID | None = None
    old_team_id: UUID | None = None
    resource_id: UUID | None = None
    resource_version: int | None = None
    owner_resource_revision: int | None = None
    quota_revision: int | None = None
    reservation_revision: int | None = None
    runtime_revision: int | None = None
    job_version: int | None = None
    job_status: str | None = None
    native_import_version: int | None = None
    native_project_id: str | int | None = None
    source_file_version: int | None = None
    source_file_object_id: UUID | None = None
    session_version: int | None = None
    approved: bool | None = None
    enabled: bool | None = None
    artifact_confirmed: bool | None = None
    reconciliation_required: bool | None = None
    cleanup_required: bool | None = None
    over_limit: bool | None = None
    # Public display locator may name an operation-wide target, not an identity.
    object_id: str | None = None


@dataclass(frozen=True, slots=True)
class ScopeIdentity:
    kind: str
    scope_id: UUID

    def __post_init__(self) -> None:
        if self.kind not in KINDS or self.scope_id.version != 4:
            raise ValueError("invalid Project/Team/User scope cursor")


@dataclass(frozen=True, slots=True)
class ScopeProvenance:
    project_uuid: UUID | None
    owner_kind: str | None
    owner_uuid: UUID | None
    team_uuids: tuple[UUID, ...]
    user_uuids: tuple[UUID, ...]
    object_uuid: UUID | None

    def scopes(self, event_name: str) -> tuple[ScopeIdentity, ...]:
        found: set[ScopeIdentity] = set()
        if self.project_uuid is not None:
            found.add(ScopeIdentity("project", self.project_uuid))
        if self.owner_uuid is not None and self.owner_kind in {"project", "team"}:
            found.add(ScopeIdentity(self.owner_kind, self.owner_uuid))
        found.update(ScopeIdentity("team", identifier) for identifier in self.team_uuids)
        if event_name.startswith(("project.", "team.owner_transferred")):
            found.update(ScopeIdentity("user", identifier) for identifier in self.user_uuids)
        self._object_scope(event_name, found)
        return tuple(sorted(found, key=lambda scope: (scope.kind, str(scope.scope_id))))

    def _object_scope(self, event_name: str, found: set[ScopeIdentity]) -> None:
        if self.object_uuid is None:
            return
        if event_name in {"team.created", "team.owner_transferred"} and not any(
            scope.kind == "team" for scope in found
        ):
            found.add(ScopeIdentity("team", self.object_uuid))
        if (
            event_name in {"team.member_added", "team.member_removed"}
            or event_name in _IDENTITY_EVENTS
        ):
            found.add(ScopeIdentity("user", self.object_uuid))
