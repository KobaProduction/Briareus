"""Source selection is bound to one original operation and current owner fences."""

from __future__ import annotations as annotations

from dataclasses import dataclass as dataclass
from datetime import datetime as datetime
from typing import Literal as Literal
from uuid import UUID as UUID

from modules.project_runtime.domain.authorization import ProjectAccessDenied as ProjectAccessDenied
from modules.project_runtime.domain.authorization import ProjectInvocation as ProjectInvocation
from modules.project_runtime.domain.authorization import (
    ProjectOperationScope as ProjectOperationScope,
)
from modules.project_runtime.domain.authorization import ProjectOwnerFence as ProjectOwnerFence
from modules.project_runtime.domain.authorization import ProjectPermit as ProjectPermit
from modules.project_runtime.domain.identifiers import valid_uuid as valid_uuid
from modules.project_runtime.domain.timestamps import aware_timestamp as aware_timestamp
from source_control.domain.source_selection import SourceSelectionRules as _SourceSelectionRules
from source_control.domain.source_selection import SVCAction as SVCAction
from source_control.domain.source_selection import SVCProvider as SVCProvider
from source_control.domain.source_selection import SVCSourceSelection as _SVCSourceSelection
from source_control.domain.source_selection import VerifiedSVCPeer as _VerifiedSVCPeer

SVC_SOURCE_HANDLERS: dict[SVCProvider, tuple[str, str]] = {
    "github": ("modules.github.runtime", "mcp"),
    "gitlab": ("modules.gitlab.runtime", "mcp"),
}


class SVCUnavailable(ProjectAccessDenied):
    """No source-proven authorization to select or invoke an SVC handler."""


@dataclass(frozen=True, slots=True)
class VerifiedSVCPeer(_VerifiedSVCPeer):
    """Result ONLY from an injected signed C2 and consumed-JTI verifier.

    Merely constructing these fields cannot establish network peer identity.
    Source composition has NO signer and cannot instantiate this port itself.
    """

    _unavailable = SVCUnavailable


@dataclass(frozen=True, slots=True)
class SVCSourceSelection(_SVCSourceSelection):
    """Privately approved source label; NEVER a tool call or access token."""


_SOURCE_RULES = _SourceSelectionRules[VerifiedSVCPeer](
    lambda provider: provider in SVC_SOURCE_HANDLERS,
    SVCUnavailable,
)
require_original_scope = _SOURCE_RULES.require_original_scope
require_initial_grant = _SOURCE_RULES.require_initial_grant
require_refreshed_grant = _SOURCE_RULES.require_refreshed_grant
