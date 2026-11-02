"""Canonical exact Hand resource selectors and current owner evidence."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from authorization.domain.action_audiences import HAND_EFFECT_ACTIONS
from authorization.domain.sessions import SessionResourceGrant

HandName = Literal["files", "terminal", "web", "svc", "reverse", "infrastructure", "serena"]

_KINDS = {
    "files": frozenset({"workspace_path"}),
    "terminal": frozenset({"workspace", "job"}),
    "serena": frozenset({"workspace"}),
    "web": frozenset({"browser_session", "origin"}),
    "svc": frozenset({"repository"}),
    "reverse": frozenset({"analysis_project", "artifact"}),
    "infrastructure": frozenset({"application"}),
}
# Authorization owns the admitted resource vocabulary. Node signs the resolved
# selector; membership in this vocabulary alone never supplies owner authority.
_NODE_STORAGE_KINDS = {
    "files": "workspace_path",
    "terminal": "workspace",
    "web": "browser_session",
    "svc": "repository",
    "infrastructure": "application",
    "reverse": "analysis_project",
    "serena": "workspace",
}
_TOOL = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}")
_FILE_PATH = re.compile(
    r"project-path-v1:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):([0-9a-f]{64})",
    re.ASCII,
)
_FILE_WORKSPACE = re.compile(r"project-files:([0-9a-f-]{36}):([0-9a-f]{64})", re.ASCII)
_NODE_STORAGE = re.compile(r"project-([a-z0-9]+):([0-9a-f-]{36}):([0-9a-f]{64})", re.ASCII)


@dataclass(frozen=True, slots=True)
class ResourceSelector:
    kind: str
    identifier: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.kind):
            raise ValueError("resource selector must be canonical")
        if not 1 <= len(self.identifier) <= 512 or self.identifier.strip() != self.identifier:
            raise ValueError("resource selector must be canonical")
        if not unicodedata.is_normalized("NFC", self.identifier):
            raise ValueError("resource selector must be canonical")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.identifier):
            raise ValueError("resource selector must be canonical")

    def validate(self, hand: str, tool: str, action: str | None = None) -> None:
        if self.kind not in _KINDS.get(hand, frozenset()) or _TOOL.fullmatch(tool) is None:
            raise ValueError("unsupported Hand/tool/resource selector")
        self._files_project(hand)
        if action is not None and action not in HAND_EFFECT_ACTIONS.get(hand, frozenset()):
            raise ValueError("action cannot be executed by this Hand")

    def _files_project(self, hand: str) -> UUID | None:
        if self.identifier.startswith("project-files:"):
            match = _FILE_WORKSPACE.fullmatch(self.identifier)
        elif self.identifier.startswith("project-path-"):
            match = _FILE_PATH.fullmatch(self.identifier)
        else:
            return None
        if hand != "files" or self.kind != "workspace_path" or match is None:
            raise ValueError("Invalid Files workspace selector")
        return _canonical_project(match.group(1))

    def require_project(self, project_uuid: UUID, hand: str, tool: str) -> None:
        self.validate(hand, tool)
        selected = self._files_project(hand)
        if selected is None and self.identifier.startswith("project-"):
            selected = self._node_project(hand)
        if selected is not None and selected != project_uuid:
            raise ValueError("Resource selector belongs to another Project")

    def _node_project(self, hand: str) -> UUID | None:
        match = _NODE_STORAGE.fullmatch(self.identifier)
        reserved = any(self.identifier.startswith("project-" + name + ":") for name in _KINDS)
        if reserved and match is None:
            raise ValueError("Malformed reserved Node module resource selector")
        if match is None or match.group(1) not in _KINDS:
            return None
        selected = _canonical_project(match.group(2))
        if match.group(1) != hand or self.kind != _NODE_STORAGE_KINDS[hand]:
            raise ValueError("Invalid Node module storage selector")
        return selected

    def key(self, hand: str, tool: str) -> str:
        self.validate(hand, tool)
        return json.dumps(
            [hand, tool, self.kind, self.identifier], ensure_ascii=True, separators=(",", ":")
        )


def _canonical_project(raw: str) -> UUID:
    project = UUID(raw)
    if project.version != 4 or str(project) != raw:
        raise ValueError("Resource selector Project must be canonical UUIDv4")
    return project


def canonical_grants(
    grants: tuple[SessionResourceGrant, ...],
    allowed_actions: set[str],
    project_uuid: UUID | None,
    *,
    unique: bool = True,
) -> tuple[SessionResourceGrant, ...]:
    for grant in grants:
        if grant.action not in allowed_actions:
            raise ValueError("resource scope exceeds approved action")
        selector = ResourceSelector(grant.resource_kind, grant.resource_id)
        selector.validate(grant.hand, grant.tool, grant.action)
        if project_uuid is not None:
            selector.require_project(project_uuid, grant.hand, grant.tool)
    if unique and len(set(grants)) != len(grants):
        raise ValueError("duplicate resource grant selector")
    return tuple(
        sorted(
            grants,
            key=lambda grant: (
                grant.hand,
                grant.tool,
                grant.action,
                grant.resource_kind,
                grant.resource_id,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class CurrentResourceProof:
    project_uuid: UUID
    grant: SessionResourceGrant
    revision: int
    expires_at: datetime

    def matches(self, requested: SessionResourceGrant, project_uuid: UUID, now: datetime) -> bool:
        selector = ResourceSelector(self.grant.resource_kind, self.grant.resource_id)
        selector.validate(self.grant.hand, self.grant.tool, self.grant.action)
        selector.require_project(project_uuid, self.grant.hand, self.grant.tool)
        same_scope = self.project_uuid == project_uuid and self.grant == requested
        current = self.expires_at.tzinfo is not None and now < self.expires_at <= now + timedelta(
            seconds=30
        )
        return same_scope and self.revision >= 1 and current
