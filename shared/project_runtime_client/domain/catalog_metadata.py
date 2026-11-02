"""Resource provenance and secret-free catalog selection rules."""

from dataclasses import dataclass
from typing import Literal, TypeGuard
from uuid import UUID

from .authorization import ProjectAccessDenied, ProjectPermit
from .resource_scope import EffectiveResourceScope
from .resources import (
    IntegrationProvider,
    ProjectIntegrationError,
    ProjectIntegrationRef,
    ProjectVariableRef,
)
from .revisions import valid_project_revision


def _integration_provider(value: str | None) -> TypeGuard[IntegrationProvider]:
    return value in {"github", "gitlab", "coolify", "signoz"}


@dataclass(frozen=True, slots=True)
class CatalogResourceFacts:
    resource_id: UUID
    name: str
    version: int
    project_access_revision: str | None
    owner_scope: Literal["team", "project"]
    owner_id: UUID
    origin: Literal["team", "project"]
    inherited: bool
    is_secret: bool
    masked: bool
    value_present: bool
    provider: str | None
    auth_type: str | None

    def scope_for(self, permit: ProjectPermit) -> EffectiveResourceScope:
        if (
            not valid_project_revision(permit.project_access_revision)
            or permit.project_owner_scope not in {"team", "project"}
            or not isinstance(permit.project_owner_id, UUID)
            or self.project_access_revision != permit.project_access_revision
            or self.owner_scope != self.origin
            or self.inherited != (self.owner_scope == "team")
            or (self.is_secret and (not self.masked or self.value_present))
        ):
            raise ProjectAccessDenied("A4_RESOURCE_SCOPE_INVALID")
        revision = permit.project_access_revision
        if not isinstance(revision, str):
            raise ProjectAccessDenied("A4_RESOURCE_REVISION_INVALID")
        scope = EffectiveResourceScope(
            effective_project_id=permit.project_id,
            owner_project_id=self.owner_id if self.owner_scope == "project" else None,
            owner_team_id=self.owner_id if self.owner_scope == "team" else None,
            project_owner_team_id=(
                permit.project_owner_id if permit.project_owner_scope == "team" else None
            ),
            resource_revision=self.version,
            project_access_revision=revision,
        )
        scope.verify_for(permit.project_id)
        return scope

    def integration_for(self, permit: ProjectPermit) -> ProjectIntegrationRef:
        provider = self.provider
        if not _integration_provider(provider) or not self.auth_type:
            raise ProjectIntegrationError("PROJECT_PROVIDER_INVALID")
        return ProjectIntegrationRef(
            scope=self.scope_for(permit),
            integration_id=self.resource_id,
            provider=provider,
            credential_type=self.auth_type,
            allowed_operations=frozenset({"read"}),
            name=self.name,
        )

    def variable_for(self, permit: ProjectPermit) -> ProjectVariableRef:
        return ProjectVariableRef(
            scope=self.scope_for(permit),
            variable_id=self.resource_id,
            kind="secret" if self.is_secret else "configuration",
            name=self.name,
        )


def require_current_catalog_permit(initial: ProjectPermit, current: ProjectPermit) -> None:
    if (
        current.actor_id != initial.actor_id
        or current.session_uuid != initial.session_uuid
        or current.project_access_revision != initial.project_access_revision
        or current.project_owner_scope != initial.project_owner_scope
        or current.project_owner_id != initial.project_owner_id
        or current.owner_fence != initial.owner_fence
    ):
        raise ProjectAccessDenied("A4_PROJECT_SCOPE_STALE")
