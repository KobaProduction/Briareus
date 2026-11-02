"""Current workspace binding and continuation rights bound to one exact effect."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from authorization.domain.resource_scopes import HandName


class WorkspaceGrantDenied(Exception):
    """The exact current effect or one of its continuation rights was revoked."""


@dataclass(frozen=True, slots=True)
class WorkspaceCall:
    module: HandName
    project_uuid: UUID
    agent_session_uuid: UUID
    node_uuid: UUID
    placement_uuid: UUID
    request_uuid: UUID
    fingerprint: str
    method: str
    tool: str | None
    original_tool: str | None
    expected_grant_revision: int
    body_digest: str
    bearer_digest: str
    arguments_digest: str
    delegated_tool: str | None = None

    def continuation_tools(self) -> tuple[str, ...]:
        source = self._source_operation_tools()
        if source is not None:
            return source
        if self.module == "reverse" and self.tool == "analysis_poll":
            return ("analysis_start",)
        if self.module not in {"web", "serena", "svc", "infrastructure"}:
            return ()
        start, poll = self.module + "_operation_start", self.module + "_operation_poll"
        if self.tool not in {start, poll}:
            return ()
        original = self.original_tool
        if (
            original is None
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", original, re.ASCII) is None
            or original.startswith(self.module + "_operation_")
        ):
            raise ValueError("Actual original module tool required")
        return (original, start) if self.tool == poll else (original,)

    def _source_operation_tools(self) -> tuple[str, ...] | None:
        direct = self.module == "svc" and self.tool == "source_control"
        started = (
            self.module == "svc"
            and self.tool == "svc_operation_start"
            and self.original_tool == "source_control"
        )
        if direct or started:
            selected = self.delegated_tool
            if (
                selected is None
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", selected, re.ASCII) is None
                or selected in {"source_control", "source_control_capabilities"}
                or selected.startswith("svc_operation_")
            ):
                raise ValueError("Exact underlying Source Control operation grant required")
            return (selected,) if direct else ("source_control", selected)
        if self.delegated_tool is not None:
            raise ValueError("Unexpected delegated operation")
        if (
            self.module == "svc"
            and self.tool in {"svc_operation_poll", "svc_operation_cancel"}
            and self.original_tool == "source_control"
        ):
            raise ValueError("Use the returned original provider operation tool")
        return None


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    issuer: str
    subject: str
    actor_uuid: UUID
    actor_expires_at: datetime
    provider_expires_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    project_uuid: UUID
    node_uuid: UUID
    placement_uuid: UUID
    workspace_uuid: UUID
    resource_revision: int
    fingerprint: str
    effect_verify_key: str
    expires_at: int
    resource_id: str
    canonical_resource_id: str

    def require_human_current(self, project_uuid: UUID, public_key: str, now: int) -> None:
        if (
            self.project_uuid != project_uuid
            or self.effect_verify_key != public_key
            or not now < self.expires_at <= now + 5
            or self.resource_id != self.canonical_resource_id
        ):
            raise ValueError("Current human browser binding mismatch")

    def require_current(self, call: WorkspaceCall, public_key: str, now: int) -> None:
        selected = (call.project_uuid, call.node_uuid, call.placement_uuid, call.fingerprint)
        actual = (self.project_uuid, self.node_uuid, self.placement_uuid, self.fingerprint)
        if (
            actual != selected
            or self.effect_verify_key != public_key
            or not now < self.expires_at <= now + 5
            or self.resource_id != self.canonical_resource_id
        ):
            raise ValueError("Current Files binding mismatch")


@dataclass(frozen=True, slots=True)
class PrivateInvocation:
    context: bytes
    expires_at: int


@dataclass(frozen=True, slots=True)
class WorkspaceEffectLease:
    call: WorkspaceCall
    identity: WorkspaceIdentity
    binding: WorkspaceBinding
    grant_revision: int
    issued_at: int
    expires_at: int
    context_digest: str


def lease_expiry(
    now: int,
    grant_expires_at: datetime,
    binding: WorkspaceBinding,
    invocation: PrivateInvocation,
) -> int:
    expiry = min(
        now + 5, int(grant_expires_at.timestamp()), binding.expires_at, invocation.expires_at
    )
    if expiry <= now:
        raise ValueError("Files authority expired")
    return expiry
