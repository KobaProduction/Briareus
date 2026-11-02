"""Finite Resources audit records; each event keeps its own required facts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, TypeAdapter

from common.infrastructure.audit_records import CatalogAudit
from node_protocol.diagnostics import FailureDiagnostic
from projects.domain.node_administration import NodeScopeKind
from projects.domain.runtime_settings import RuntimeSetting


class ProviderConnectionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str


class WorkspaceAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_uuid: UUID
    purpose: Literal["workspace"] = "workspace"


class NodeScopeAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: NodeScopeKind


class RuntimeSettingsAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    keys: tuple[RuntimeSetting, ...]


class PlacementAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_uuid: UUID
    phase: str
    diagnostic: FailureDiagnostic | None = None
    restored_fingerprint: str | None = None


class ModulePublicationAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact: str
    image: str
    source_commit: str
    definition_upgrade: str | None = None


type ResourcesAudit = (
    CatalogAudit
    | ProviderConnectionAudit
    | WorkspaceAudit
    | NodeScopeAudit
    | RuntimeSettingsAudit
    | PlacementAudit
    | ModulePublicationAudit
)

RESOURCES_AUDIT = TypeAdapter[ResourcesAudit](ResourcesAudit)
