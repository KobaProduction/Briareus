"""Exact placement and effect binding required before a Node invocation."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .admission import McpAdmission

type NodeModule = Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"]


def node_module(value: str) -> NodeModule:
    match value:
        case "files" | "terminal" | "web" | "svc" | "infrastructure" | "reverse" | "serena":
            return value
    raise ValueError("Executable Node module required")


@dataclass(frozen=True, slots=True)
class NodePlacement:
    node_uuid: UUID
    placement_uuid: UUID
    project_uuid: UUID
    module: NodeModule
    fingerprint: str
    port: int
    origin: str
    expires_at: int

    def require_current(self, admission: McpAdmission, origins: frozenset[str], now: int) -> None:
        if (
            self.project_uuid != admission.project_uuid
            or self.module != admission.hand
            or self.origin not in origins
            or not now < self.expires_at <= now + 5
        ):
            raise ValueError("Wrong or expired authoritative node route")


@dataclass(frozen=True, slots=True)
class AuthorityEvidence:
    permit: str
    context: str


@dataclass(frozen=True, slots=True)
class EffectBinding:
    node_uuid: UUID
    placement_uuid: UUID
    project_uuid: UUID
    module: NodeModule
    fingerprint: str
    agent_session_uuid: UUID
    grant_revision: int
    request_uuid: UUID
    body_digest: str
    bearer_digest: str
    context_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedEffect:
    evidence: AuthorityEvidence
    binding: EffectBinding


@dataclass(frozen=True, slots=True)
class PreparedForward:
    target: str
    permit: str
    proof: str
    signature: str
    context: str


def operation_selector(method: str | None, selector: str | int | None) -> UUID | None:
    if method != "tools/call" or not isinstance(selector, str):
        return None
    try:
        selected = UUID(selector)
    except ValueError:
        return None
    return selected if selected.version == 4 and str(selected) == selector else None


def require_effect_binding(actual: EffectBinding, expected: EffectBinding) -> None:
    if actual != expected:
        raise ValueError("Effect authority changed request or credential context")
