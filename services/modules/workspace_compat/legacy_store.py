"""Stable imports for the typed legacy workspace filesystem adapter.

This store is not the protected Project Files authority boundary.
"""

from .domain.transfers import WorkspaceFileError as WorkspaceFileError
from .infrastructure.filesystem import WorkspaceFileStore as WorkspaceFileStore
