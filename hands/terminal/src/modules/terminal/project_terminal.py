"""Compatibility API for the canonical typed Terminal technical client."""

from __future__ import annotations

from uuid import UUID as UUID

from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from modules.project_runtime.workspace_roots import ProjectRootRegistry as ProjectRootRegistry
from project_runtime_client.terminal.project_terminal import (
    ProjectTerminalExecutionUnavailable as ProjectTerminalExecutionUnavailable,
)
from project_runtime_client.terminal.project_terminal import (
    ProjectTerminalRuntime as ProjectTerminalRuntime,
)

from .project_isolation import ProjectIsolationAttestation as ProjectIsolationAttestation
from .project_isolation import ProjectIsolationInspector as ProjectIsolationInspector
