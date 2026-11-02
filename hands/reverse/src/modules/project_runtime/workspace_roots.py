"""Compatibility exports for the shared project runtime client implementation."""

from project_runtime_client.domain.workspace import ProjectFileError as ProjectFileError
from project_runtime_client.infrastructure.workspace_roots import _DIR_FLAGS as _DIR_FLAGS
from project_runtime_client.infrastructure.workspace_roots import (
    ProjectRootRegistry as ProjectRootRegistry,
)
from project_runtime_client.infrastructure.workspace_roots import _open_beneath as _open_beneath
from project_runtime_client.infrastructure.workspace_roots import _safe_directory as _safe_directory
from project_runtime_client.workspace_roots import __all__ as __all__
