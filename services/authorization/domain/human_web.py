"""Human browser authority derives from current identity and project ownership."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from .workspace_effects import WorkspaceBinding, WorkspaceIdentity


@dataclass(frozen=True, slots=True)
class HumanCall:
    project_uuid: UUID
    request_uuid: UUID
    method: str
    tool: str | None
    original_tool: str | None
    body_digest: str
    bearer_digest: str
    arguments_digest: str
    module: Literal["web", "files", "terminal", "reverse"] = "web"

    action: Literal[
        "web.access", "files.read", "files.write", "terminal.execute", "analysis.import"
    ] = "web.access"

    def required_tools(self) -> tuple[str, ...]:
        if self.tool is None:
            return ()
        if self.module == "reverse" and self.tool in {"analysis_poll", "analysis_cancel"}:
            return (self.tool, "analysis_start")
        if self.tool not in {"web_operation_start", "web_operation_poll"}:
            return (self.tool,)
        original = self.original_tool
        if (
            original is None
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", original, re.ASCII) is None
            or original.startswith("web_operation_")
        ):
            raise ValueError("Exact original human browser tool required")
        return (self.tool, original, "web_operation_start")


@dataclass(frozen=True, slots=True)
class HumanIdentity:
    identity: WorkspaceIdentity
    project_uuid: UUID
    permissions: tuple[str, ...]

    def require_current(self, project: UUID, now: datetime) -> None:
        if (
            self.project_uuid != project
            or "use_resources" not in self.permissions
            or self.identity.actor_expires_at <= now
            or self.identity.provider_expires_at <= now
        ):
            raise PermissionError("Current human project authority required")


@dataclass(frozen=True, slots=True)
class HumanResource:
    resource_id: str
    tools: frozenset[str]

    def require_call(self, call: HumanCall, binding: WorkspaceBinding) -> None:
        if (
            self.resource_id != binding.resource_id
            or not self.tools
            or not set(call.required_tools()) <= self.tools
        ):
            raise PermissionError("Current human browser resource required")


@dataclass(frozen=True, slots=True)
class HumanDecision:
    actor_uuid: UUID
    project_uuid: UUID
    resource_id: str
    current_project_access: bool
    current_owner_scope: bool
    action: Literal[
        "web.access", "files.read", "files.write", "terminal.execute", "analysis.import"
    ] = "web.access"


@dataclass(frozen=True, slots=True)
class HumanLease:
    call: HumanCall
    identity: WorkspaceIdentity
    binding: WorkspaceBinding
    issued_at: int
    expires_at: int
