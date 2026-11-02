"""Compatibility API for the canonical shared Files client implementation."""

import asyncio as asyncio
import hashlib as hashlib
from collections.abc import AsyncIterator as AsyncIterator
from collections.abc import Callable as Callable
from contextlib import asynccontextmanager as asynccontextmanager
from contextlib import suppress as suppress
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Literal as Literal
from uuid import UUID as UUID

from modules.project_runtime import ProjectAccessDenied as ProjectAccessDenied
from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectPermit as ProjectPermit
from modules.project_runtime import ProjectRootRegistry as ProjectRootRegistry
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from project_runtime_client.files.service import ProjectFilesService as _SharedProjectFilesService
from project_runtime_client.files.service import (
    _drain_cancellable_file_io as _drain_cancellable_file_io,
)
from project_runtime_client.files.service import _write_reserved_chunks as _write_reserved_chunks

from .a6_signed import A6FilesUnavailable as A6FilesUnavailable
from .a6_signed import A6SignedFilesFlow as A6SignedFilesFlow
from .a6_signed import canonical_files_path as canonical_files_path
from .a14_read_witness import A14FilesReadPreflight as A14FilesReadPreflight
from .a14_read_witness import FilesReadBusinessPreimage as FilesReadBusinessPreimage
from .project_workspace import ProjectFileEntry as ProjectFileEntry
from .project_workspace import ProjectFilePage as ProjectFilePage
from .project_workspace import ProjectFileSnapshot as ProjectFileSnapshot
from .project_workspace import ProjectFileWriteStage as ProjectFileWriteStage
from .project_workspace import ProjectWorkspaceFiles as ProjectWorkspaceFiles


class ProjectFilesService(_SharedProjectFilesService[A6SignedFilesFlow]):
    """Keep the owner-local Files service and exact signed-quota type."""

    _quota_type = A6SignedFilesFlow
