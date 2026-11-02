"""The deployed human Node command schema, independent of route composition."""

from datetime import datetime
from typing import Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, field_validator

from node_protocol import NodeBudget
from node_protocol.management import ModuleCommand
from node_protocol.models import RuntimePolicyOverrides
from projects.domain.node_administration import NodeScopeKind, node_name
from projects.domain.node_control import NodeOrigin


class NodeRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID4
    name: str = Field(min_length=1, max_length=128)
    scope: NodeScopeKind
    owner_uuid: UUID4 | None = None
    host_uuid: UUID4
    runtime_uid: int = Field(strict=True, ge=2000, le=2**31 - 1)
    endpoint: str = Field(max_length=512)
    budget: NodeBudget

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return node_name(value)

    @field_validator("endpoint")
    @classmethod
    def endpoint_valid(cls, value: str) -> str:
        return NodeOrigin(value).value


class NodeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    actor_uuid: UUID4
    project_uuid: UUID4
    identity_expires_at: datetime
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
