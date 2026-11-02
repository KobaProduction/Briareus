"""Verified resource metadata and the rules for using its provenance."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from project_runtime_client.domain._code_error import _CodeError

from .identifiers import valid_uuid
from .resource_scope import EffectiveResourceScope, ProjectResourceScopeError

VariableKind = Literal["configuration", "secret"]
IntegrationProvider = Literal["github", "gitlab", "coolify", "signoz"]
IntegrationOperation = Literal["read", "write"]
IntegrationAction = Literal["infrastructure.read", "svc.read", "svc.write"]


class ProjectVariableError(_CodeError):
    pass


class ProjectIntegrationError(_CodeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectVariableRef:
    """MCP-visible metadata deliberately contains no plaintext value."""

    scope: EffectiveResourceScope
    variable_id: UUID
    kind: VariableKind
    name: str

    @property
    def resource_id(self) -> UUID:
        return self.variable_id

    def require_access(
        self,
        *,
        project_uuid: UUID,
        access_revision: str | None,
        variable_uuid: UUID | None = None,
    ) -> None:
        if not isinstance(self.name, str):
            raise ProjectVariableError("PROJECT_VARIABLE_ACCESS_DENIED")
        if (
            not valid_uuid(self.variable_id)
            or (variable_uuid is not None and self.variable_id != variable_uuid)
            or self.kind not in {"configuration", "secret"}
            or not self.name.strip()
        ):
            raise ProjectVariableError("PROJECT_VARIABLE_ACCESS_DENIED")
        try:
            self.scope.verify_for(project_uuid)
            if self.scope.project_access_revision != access_revision:
                raise ProjectResourceScopeError("RESOURCE_SCOPE_STALE")
        except (ProjectResourceScopeError, AttributeError, TypeError) as exc:
            raise ProjectVariableError("PROJECT_VARIABLE_ACCESS_DENIED") from exc


@dataclass(frozen=True, slots=True)
class ProjectIntegrationRef:
    """Stable identity and verified provenance; never a raw API credential."""

    scope: EffectiveResourceScope
    integration_id: UUID
    provider: IntegrationProvider
    credential_type: str
    allowed_operations: frozenset[IntegrationOperation]
    name: str = ""

    @property
    def resource_id(self) -> UUID:
        return self.integration_id

    def require_access(
        self,
        *,
        project_uuid: UUID,
        access_revision: str | None,
        provider: IntegrationProvider,
        operation: IntegrationOperation,
        integration_uuid: UUID | None = None,
    ) -> None:
        if (
            not valid_uuid(self.integration_id)
            or (integration_uuid is not None and self.integration_id != integration_uuid)
            or self.provider != provider
            or operation not in self.allowed_operations
            or not self.credential_type
        ):
            raise ProjectIntegrationError("PROJECT_INTEGRATION_ACCESS_DENIED")
        try:
            self.scope.verify_for(project_uuid)
            if self.scope.project_access_revision != access_revision:
                raise ProjectResourceScopeError("RESOURCE_SCOPE_STALE")
        except (ProjectResourceScopeError, AttributeError, TypeError) as exc:
            raise ProjectIntegrationError("PROJECT_INTEGRATION_ACCESS_DENIED") from exc


def integration_action(
    provider: IntegrationProvider,
    operation: IntegrationOperation,
) -> IntegrationAction:
    if provider not in {"github", "gitlab", "coolify", "signoz"}:
        raise ProjectIntegrationError("PROJECT_PROVIDER_INVALID")
    if operation not in {"read", "write"}:
        raise ProjectIntegrationError("PROJECT_INTEGRATION_ACTION_INVALID")
    if provider in {"coolify", "signoz"}:
        if operation != "read":
            raise ProjectIntegrationError("PROJECT_INTEGRATION_WRITE_UNAVAILABLE")
        return "infrastructure.read"
    return "svc.write" if operation == "write" else "svc.read"
