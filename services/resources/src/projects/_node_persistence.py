"""Resources-owned node placement metadata; cross-owner identities are UUID refs.

Configuration contains public settings and credential references only. Node
private keys, Rauthy credentials and provider tokens never belong in these rows.
"""

from datetime import UTC, datetime
from functools import partial
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from common.platform_db import CatalogBase
from node_protocol import Deployment, NodeBudget, ResourceLimits
from node_protocol.models import RuntimePolicyOverrides
from projects.infrastructure.catalog_records import InputPayload
from projects.infrastructure.model_jsonb import ModelJSONB
from projects.infrastructure.node_storage_models import (
    ArtifactConfigurationContract,
    ArtifactStorageContract,
    PlacementCreationMetadata,
)

now = partial(datetime.now, UTC)


class NodeRow(CatalogBase):
    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint("scope IN ('personal','team','shared')", name="ck_node_scope"),
        CheckConstraint("(scope = 'shared') = (owner_uuid IS NULL)", name="ck_node_scope_owner"),
        CheckConstraint("sequence > 0", name="ck_node_sequence"),
        CheckConstraint("runtime_uid >= 2000", name="ck_node_runtime_uid"),
        UniqueConstraint("host_uuid", "runtime_uid", name="uq_node_host_runtime_uid"),
        Index("ix_node_owner", "scope", "owner_uuid"),
        {"schema": "resources"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(16))
    owner_uuid: Mapped[UUID | None] = mapped_column()
    host_uuid: Mapped[UUID] = mapped_column()
    runtime_uid: Mapped[int] = mapped_column(Integer)
    endpoint: Mapped[str] = mapped_column(String(512))
    public_key: Mapped[str | None] = mapped_column(Text)
    credential_reference: Mapped[str | None] = mapped_column(String(128))
    budget: Mapped[NodeBudget] = mapped_column(ModelJSONB(NodeBudget))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sequence: Mapped[int] = mapped_column(BigInteger, default=1)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NodeBindingRow(CatalogBase):
    __tablename__ = "node_bindings"
    __table_args__ = (
        CheckConstraint(
            "subject_kind IN ('user','team','authenticated')", name="ck_node_binding_subject"
        ),
        CheckConstraint(
            "(subject_kind = 'authenticated') = (subject_uuid IS NULL)", name="ck_node_binding_uuid"
        ),
        CheckConstraint("capability IN ('use','manage')", name="ck_node_binding_capability"),
        Index(
            "uq_node_binding",
            "node_uuid",
            "subject_kind",
            "subject_uuid",
            "capability",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "resources"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    node_uuid: Mapped[UUID] = mapped_column(ForeignKey("resources.nodes.id", ondelete="RESTRICT"))
    subject_kind: Mapped[str] = mapped_column(String(16))
    subject_uuid: Mapped[UUID | None] = mapped_column()
    capability: Mapped[str] = mapped_column(String(16))


class ModuleArtifactRow(CatalogBase):
    __tablename__ = "module_artifacts"
    __table_args__ = ({"schema": "resources"},)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    inputs: Mapped[InputPayload | None] = mapped_column(
        ModelJSONB(InputPayload, invalid_as_none=True), nullable=False
    )
    configuration_contract: Mapped[ArtifactConfigurationContract] = mapped_column(
        ModelJSONB(ArtifactConfigurationContract)
    )
    storage_contract: Mapped[ArtifactStorageContract] = mapped_column(
        ModelJSONB(ArtifactStorageContract)
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class ModuleReleaseRow(CatalogBase):
    __tablename__ = "module_releases"
    __table_args__ = (
        UniqueConstraint("id", "artifact_key", name="uq_node_release_artifact"),
        UniqueConstraint(
            "artifact_key",
            "source_commit",
            "platform",
            "input_fingerprint",
            name="uq_node_release_build",
        ),
        CheckConstraint("state IN ('building','published','failed')", name="ck_node_release_state"),
        CheckConstraint("source_commit ~ '^[a-f0-9]{40}$'", name="ck_node_release_commit"),
        CheckConstraint(
            "state <> 'published' OR image_reference IS NOT NULL", name="ck_node_release_image"
        ),
        {"schema": "resources"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    artifact_key: Mapped[str] = mapped_column(
        ForeignKey("resources.module_artifacts.key", ondelete="RESTRICT")
    )
    source_commit: Mapped[str] = mapped_column(String(40))
    platform: Mapped[str] = mapped_column(String(32))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    image_reference: Mapped[str | None] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(16), default="building")
    build_reference: Mapped[str | None] = mapped_column(String(128))
    storage_compatibility: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NodeStorageRow(CatalogBase):
    __tablename__ = "node_storage"
    __table_args__ = (
        UniqueConstraint("id", "node_uuid", "project_uuid", name="uq_node_storage_scope"),
        UniqueConstraint("node_uuid", "project_uuid", "purpose", name="uq_node_storage_purpose"),
        CheckConstraint("quota_bytes > 0", name="ck_node_storage_quota"),
        CheckConstraint("retention IN ('persistent','cache')", name="ck_node_storage_retention"),
        {"schema": "resources"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    node_uuid: Mapped[UUID] = mapped_column(ForeignKey("resources.nodes.id", ondelete="RESTRICT"))
    project_uuid: Mapped[UUID] = mapped_column()
    purpose: Mapped[str] = mapped_column(String(64))
    quota_bytes: Mapped[int] = mapped_column(BigInteger)
    retention: Mapped[str] = mapped_column(String(16), default="persistent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NodeModuleRow(CatalogBase):
    __tablename__ = "node_modules"
    __table_args__ = (
        UniqueConstraint("id", "project_uuid", name="uq_node_module_project"),
        UniqueConstraint("id", "node_uuid", name="uq_node_module_node"),
        ForeignKeyConstraint(
            ["desired_release_uuid", "artifact_key"],
            ["resources.module_releases.id", "resources.module_releases.artifact_key"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["applied_release_uuid", "artifact_key"],
            ["resources.module_releases.id", "resources.module_releases.artifact_key"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["storage_uuid", "node_uuid", "project_uuid"],
            [
                "resources.node_storage.id",
                "resources.node_storage.node_uuid",
                "resources.node_storage.project_uuid",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0", name="ck_node_module_sequence"),
        CheckConstraint(
            "state IN ('pending','ready','updating','disabled','failed')",
            name="ck_node_module_state",
        ),
        Index("ix_node_modules_node", "node_uuid"),
        {"schema": "resources"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    node_uuid: Mapped[UUID] = mapped_column(ForeignKey("resources.nodes.id", ondelete="RESTRICT"))
    project_uuid: Mapped[UUID] = mapped_column()
    artifact_key: Mapped[str] = mapped_column(
        ForeignKey("resources.module_artifacts.key", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(128))
    desired_release_uuid: Mapped[UUID | None] = mapped_column()
    applied_release_uuid: Mapped[UUID | None] = mapped_column()
    storage_uuid: Mapped[UUID | None] = mapped_column()
    configuration: Mapped[PlacementCreationMetadata] = mapped_column(
        ModelJSONB(PlacementCreationMetadata), default=PlacementCreationMetadata
    )
    limits: Mapped[ResourceLimits] = mapped_column(ModelJSONB(ResourceLimits))
    sequence: Mapped[int] = mapped_column(BigInteger, default=1)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProjectModuleBindingRow(CatalogBase):
    __tablename__ = "project_module_bindings"
    __table_args__ = (
        UniqueConstraint("project_uuid", "logical_key", name="uq_project_module_route"),
        ForeignKeyConstraint(
            ["placement_uuid", "project_uuid"],
            ["resources.node_modules.id", "resources.node_modules.project_uuid"],
            ondelete="RESTRICT",
        ),
        {"schema": "resources"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_uuid: Mapped[UUID] = mapped_column()
    placement_uuid: Mapped[UUID] = mapped_column()
    logical_key: Mapped[str] = mapped_column(String(64))


class NodeOperationRow(CatalogBase):
    __tablename__ = "node_operations"
    __table_args__ = (
        UniqueConstraint("placement_uuid", "sequence", name="uq_node_operation_sequence"),
        ForeignKeyConstraint(
            ["placement_uuid", "node_uuid"],
            ["resources.node_modules.id", "resources.node_modules.node_uuid"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0", name="ck_node_operation_sequence"),
        CheckConstraint(
            "phase IN ('queued','building','publishing','pulling','stopping','creating',"
            "'checking','rolling_back','succeeded','failed','unknown')",
            name="ck_node_operation_phase",
        ),
        Index(
            "uq_node_operation_active",
            "placement_uuid",
            unique=True,
            postgresql_where=text("phase NOT IN ('succeeded','failed')"),
        ),
        {"schema": "resources"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    node_uuid: Mapped[UUID] = mapped_column(ForeignKey("resources.nodes.id", ondelete="RESTRICT"))
    placement_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("resources.node_modules.id", ondelete="RESTRICT")
    )
    actor_uuid: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(BigInteger)
    fingerprint: Mapped[str] = mapped_column(String(64))
    desired: Mapped[Deployment] = mapped_column(ModelJSONB(Deployment))
    previous: Mapped[Deployment | None] = mapped_column(ModelJSONB(Deployment, allow_none=True))
    phase: Mapped[str] = mapped_column(String(16), default="queued")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RuntimePolicyRow(CatalogBase):
    __tablename__ = "runtime_policies"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_runtime_policy_sequence"),
        {"schema": "resources"},
    )
    scope_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    values: Mapped[RuntimePolicyOverrides] = mapped_column(
        "policy_values", ModelJSONB(RuntimePolicyOverrides), default=RuntimePolicyOverrides
    )
    sequence: Mapped[int] = mapped_column(BigInteger, default=1)
