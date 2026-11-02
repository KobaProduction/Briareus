"""Named deployed Node management commands and owner response envelopes."""

from typing import Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field

from node_protocol import NodeBudget, NodeRecord, ResourceLimits
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.management import ModuleCommand
from node_protocol.models import (
    ModuleConfiguration,
    RuntimePolicy,
    RuntimePolicyOverrides,
    WorkspaceMount,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NodeRegistration(Contract):
    id: UUID4
    name: str
    scope: Literal["personal", "team", "shared"]
    owner_uuid: UUID4 | None = None
    host_uuid: UUID4
    runtime_uid: int
    endpoint: str
    budget: NodeBudget


class NodeInput(Contract):
    project_uuid: UUID4
    operation_uuid: UUID4
    action: Literal[
        "list",
        "register",
        "rename",
        "disable",
        "setup",
        "pair",
        "enable",
        "budget",
        "modules",
        "runtime_policy",
        "runtime_policy_get",
    ]
    registration: NodeRegistration | None = None
    node_uuid: UUID4 | None = None
    name: str = Field(default="", max_length=128)
    expected_sequence: int | None = Field(default=None, strict=True, ge=1)
    public_key: str = Field(default="", max_length=256)
    module: ModuleCommand | None = None
    budget: NodeBudget | None = None
    policy_scope: Literal["server", "node"] = "server"
    policy_values: RuntimePolicyOverrides | None = None
    expected_policy_sequence: int | None = Field(default=None, strict=True, ge=0)


class NodeSummary(Contract):
    id: str
    name: str
    scope: Literal["personal", "team", "shared"]
    owner_uuid: str | None
    host_uuid: str
    runtime_uid: int
    endpoint: str
    budget: NodeBudget
    enabled: bool
    paired: bool
    sequence: int
    last_seen_at: str | None
    created_at: str


class NodeInventory(Contract):
    items: tuple[NodeSummary, ...]
    truncated: bool


class NodeDetail(Contract):
    item: NodeSummary


class NodeJournalSetup(Contract):
    target: str = Field(min_length=3, max_length=512)
    ca_certificate: str = Field(min_length=1, max_length=65536)


class NodeSetup(Contract):
    node_record: NodeRecord
    core_verify_key: str
    gateway_verify_key: str
    runtime_uid: int
    runtime_user: str
    runtime_gid: int
    rootless_budget: ResourceLimits
    endpoint: str
    origin_approved: bool
    journal: NodeJournalSetup


class NodeInstaller(Contract):
    setup: NodeSetup


class RuntimeSources(Contract):
    execution_timeout_seconds: str
    web_max_tabs: str
    web_tab_idle_seconds: str
    terminal_idle_seconds: str


class RuntimePolicyView(Contract):
    scope: Literal["server", "node"]
    node_uuid: UUID4 | None
    sequence: int
    overrides: RuntimePolicyOverrides
    effective: RuntimePolicy
    sources: RuntimeSources
    applies_on: Literal["placement_update"]


class NodePolicy(Contract):
    runtime_policy: RuntimePolicyView


class CatalogInputs(Contract):
    dockerfile: str
    paths: tuple[str, ...]
    platform: str
    build_args: dict[str, str] | None = None


class CatalogArtifact(Contract):
    key: str
    name: str
    node_adapter: bool
    lifecycle: str
    workspace: bool
    inputs: CatalogInputs
    minimum_limits: ResourceLimits
    default_limits: ResourceLimits


class CatalogModule(Contract):
    key: str
    name: str
    components: tuple[str, ...]


class CatalogRelease(Contract):
    id: str
    module: str
    source_commit: str
    input_fingerprint: str
    image: str | None = None
    platform: str
    state: str
    created_at: str


class ModuleCatalog(Contract):
    modules: tuple[CatalogModule, ...]
    artifacts: tuple[CatalogArtifact, ...]
    releases: tuple[CatalogRelease, ...]


class PublishedRelease(Contract):
    release: CatalogRelease


class Workspace(Contract):
    id: str
    node_uuid: str
    project_uuid: str
    purpose: str
    retention: str


class WorkspaceList(Contract):
    items: tuple[Workspace, ...]


class WorkspaceDetail(Contract):
    item: Workspace | None


class PlacementOperation(Contract):
    id: str
    placement_uuid: str
    sequence: int
    phase: str
    error: str | None
    updated_at: str
    diagnostic: FailureDiagnostic | None = None
    reconciliation_required: bool | None = None
    restored: bool | None = None


class OperationReceipt(Contract):
    operation: PlacementOperation


class Placement(Contract):
    runtime_policy_pending: bool
    id: str
    node_uuid: str
    project_uuid: str
    name: str
    module: str
    state: str
    sequence: int
    limits: ResourceLimits
    workspace_uuid: str | None
    release_uuid: str
    configuration: ModuleConfiguration | None
    project_workspace: WorkspaceMount | None
    operation: PlacementOperation | None


class PlacementList(Contract):
    items: tuple[Placement, ...]


NodeOutput = (
    NodeInventory
    | NodeDetail
    | NodeInstaller
    | NodePolicy
    | ModuleCatalog
    | PublishedRelease
    | WorkspaceList
    | WorkspaceDetail
    | OperationReceipt
    | PlacementList
)
