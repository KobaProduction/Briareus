"""Bounded node configuration; no raw Docker options cross the control API."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator, model_validator, model_serializer


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NodeScope(Contract):
    kind: Literal["personal", "team", "shared"]
    owner_uuid: UUID4 | None = None

    @model_validator(mode="after")
    def owner(self):
        if (self.kind == "shared") != (self.owner_uuid is None):
            raise ValueError("Personal/team scope needs its owner; shared scope has none")
        return self


class ResourceLimits(Contract):
    memory_bytes: int = Field(strict=True, ge=16 * 1024 * 1024, le=2**50)
    cpu_millis: int = Field(strict=True, ge=10, le=1_024_000)
    pids: int = Field(strict=True, ge=16, le=1_000_000)


class NodeBudget(Contract):
    total: ResourceLimits
    reserved: ResourceLimits

    @model_validator(mode="after")
    def reserve(self):
        for field in ResourceLimits.model_fields:
            if getattr(self.reserved, field) >= getattr(self.total, field):
                raise ValueError("Control/runtime reserve must leave execution capacity")
        return self

    def fits(self, allocations: list[ResourceLimits]) -> bool:
        return all(
            getattr(self.reserved, field) + sum(getattr(item, field) for item in allocations)
            <= getattr(self.total, field)
            for field in ResourceLimits.model_fields
        )


class NodeRecord(Contract):
    id: UUID4
    name: str = Field(min_length=1, max_length=128)
    scope: NodeScope
    budget: NodeBudget
    enabled: bool = False
    # Shared availability is intentionally independent of administration.
    # Authorization evaluates these requests against current Platform actors.
    shared_use: bool = False
    shared_manage: bool = False
    created_at: datetime

    @field_validator("name")
    @classmethod
    def display_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("A printable node name is required")
        return value

    @field_validator("created_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("An explicit timestamp timezone is required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def shared_policy(self):
        if self.scope.kind != "shared" and (self.shared_use or self.shared_manage):
            raise ValueError("Public capabilities apply only to shared nodes")
        return self


class ModuleRelease(Contract):
    """Operator-approved catalogue entry, not agent-supplied Docker configuration."""

    module: Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"]
    image: str = Field(
        max_length=512,
        pattern=r"^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$",
    )
    port: int = Field(default=8000, strict=True, ge=1024, le=65535)
    health_path: Literal["/health/ready"] = "/health/ready"
    run_as: str = Field(default="1000:1000", pattern=r"^[1-9][0-9]{0,8}:[1-9][0-9]{0,8}$")
    # Explicit execution class; no default that silently kills a stateful worker.
    lifecycle: Literal["stateless", "sessionful"]


class WorkspaceMount(Contract):
    id: UUID4
    read_only: bool = False


class BrowserConfiguration(Contract):
    external_enabled: bool = False
    external_mcp_url: str = Field(default="", max_length=2048)
    call_timeout_seconds: int | None = Field(default=None,strict=True,ge=1)
    auto_disconnect_enabled: bool = False
    idle_timeout_seconds: int = Field(default=300,strict=True,ge=30,le=86400)
    profile_dir_name: str = Field(default="Default",min_length=1,max_length=128)
    developer_access_enabled: bool = False

    @model_validator(mode="after")
    def public_endpoint(self):
        from urllib.parse import urlsplit
        if self.external_mcp_url:
            parsed=urlsplit(self.external_mcp_url)
            if (parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in {None,443}):
                raise ValueError("An explicit HTTPS external MCP endpoint is required")
        if self.external_enabled and not self.external_mcp_url:
            raise ValueError("External browser requires its configured endpoint")
        if self.profile_dir_name in {".",".."} or any(ch in self.profile_dir_name for ch in "/\\\0"):
            raise ValueError("A single browser profile name is required")
        return self


class SerenaConfiguration(Contract):
    project_path: str = Field(default=".",min_length=1,max_length=512)
    language_backend: Literal["LSP"] = "LSP"

    @field_validator("project_path")
    @classmethod
    def relative_project(cls,value):
        from pathlib import PurePosixPath
        path=PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value or "\0" in value:
            raise ValueError("Serena project must stay inside its project workspace")
        return str(path)


class NetworkConfiguration(Contract):
    # Direct public TCP/UDP/DNS. Private infrastructure access is never implied.
    profile: Literal["public"] = "public"


class RuntimePolicy(Contract):
    """Resolved execution/lifecycle policy; never an authorization lifetime."""
    execution_timeout_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    web_max_tabs: int | None = Field(default=10, strict=True, ge=1, le=2**32-1)
    web_tab_idle_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    terminal_idle_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class RuntimePolicyOverrides(RuntimePolicy):
    # model_fields_set distinguishes inherit (omitted) from disabled (null).
    web_max_tabs: int | None = Field(default=None, strict=True, ge=1, le=2**32-1)

    @model_serializer(mode="wrap")
    def wire_overrides(self,handler):
        return {key:value for key,value in handler(self).items() if key in self.model_fields_set}


class ModuleConfiguration(Contract):
    runtime_policy: RuntimePolicy | None = None
    network: NetworkConfiguration | None = None
    browser: BrowserConfiguration | None = None
    serena: SerenaConfiguration | None = None

    @model_serializer(mode="wrap")
    def wire(self,handler):
        value=handler(self)
        if self.runtime_policy is None:
            value.pop("runtime_policy",None)
        if self.network is None:
            value.pop("network",None)
        return value


class Deployment(Contract):
    id: UUID4
    node_uuid: UUID4
    project_uuid: UUID4
    release: ModuleRelease
    limits: ResourceLimits
    enabled: bool = True
    workspace: WorkspaceMount | None = None
    project_workspace: WorkspaceMount | None = None
    effect_verify_key: str | None = Field(default=None,max_length=256)
    configuration: ModuleConfiguration | None = None

    @model_serializer(mode="wrap")
    def wire(self,handler):
        value=handler(self)
        # Existing pinned deployments retain their exact immutable fingerprint.
        if self.configuration is None:
            value.pop("configuration",None)
        if self.project_workspace is None:
            value.pop("project_workspace",None)
        return value

    @field_validator("effect_verify_key")
    @classmethod
    def effect_key_valid(cls,value):
        if value is None:
            return value
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key=serialization.load_pem_public_key(value.encode())
        if not isinstance(key,Ed25519PublicKey):
            raise ValueError("Pinned Ed25519 Authorization public key required")
        return key.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    @model_validator(mode="after")
    def workspace_contract(self):
        if self.project_workspace is not None:
            if self.release.module not in {"web","reverse"} or self.workspace is None or self.project_workspace.id == self.workspace.id:
                raise ValueError("Shared project workspace must be separate from private browser storage")
            if self.release.run_as != "1000:1000":
                raise ValueError("Shared browser transfers require the workspace uid")
        if self.release.module == "terminal":
            from .catalog import ARTIFACTS
            if self.workspace is None or any(getattr(self.limits,key)<value
                for key,value in {"memory_bytes":256*1024**2,"cpu_millis":200,"pids":64}.items()):
                raise ValueError("Offline Terminal needs its project workspace and minimum supervisor capacity")
        if self.workspace is not None:
            if self.release.run_as != "1000:1000":
                raise ValueError("Project workspaces require an approved workspace Hand and its shared non-root uid")
            if self.limits.memory_bytes < 64 * 1024**2 or self.limits.cpu_millis < 100 or self.limits.pids < 32:
                raise ValueError("Workspace initialization requires bounded execution capacity")
        if self.configuration is not None:
            selected={key for key,value in self.configuration.model_dump().items() if value is not None}
            expected={"web":"browser","serena":"serena","terminal":"network"}.get(self.release.module)
            selected.discard("runtime_policy")
            if selected and selected!={expected}:
                raise ValueError("Configuration belongs to another module")
        return self

    @property
    def fingerprint(self) -> str:
        wire = json.dumps(self.model_dump(mode="json", exclude={"enabled"}), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(wire.encode()).hexdigest()

    @property
    def container_name(self) -> str:
        from .naming import worker_name
        return worker_name(self.node_uuid,self.id,self.fingerprint)
