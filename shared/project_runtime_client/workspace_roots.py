"""Stable descriptor-storage imports for independently packaged Hands."""

from .domain.workspace import ProjectFileError as ProjectFileError
from .infrastructure.workspace_roots import (
    _DIR_FLAGS as _DIR_FLAGS,
)
from .infrastructure.workspace_roots import (
    ProjectRootRegistry as ProjectRootRegistry,
)
from .infrastructure.workspace_roots import (
    _open_beneath as _open_beneath,
)
from .infrastructure.workspace_roots import (
    _safe_directory as _safe_directory,
)

__all__ = [
    "_DIR_FLAGS",
    "ProjectFileError",
    "ProjectRootRegistry",
    "_open_beneath",
    "_safe_directory",
]
