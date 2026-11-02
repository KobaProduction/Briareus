"""Compatibility exports for the shared project runtime client implementation."""

import ctypes as ctypes
import errno as errno
import os as os
import platform as platform
import stat as stat
from collections.abc import Iterator as Iterator
from contextlib import contextmanager as contextmanager
from contextlib import suppress as suppress
from datetime import UTC as UTC
from datetime import datetime as datetime
from pathlib import Path as Path

from project_runtime_client.domain.authorization import ProjectPermit as ProjectPermit
from project_runtime_client.domain.workspace import ProjectFileError as ProjectFileError
from project_runtime_client.domain.workspace import project_directory_name as project_directory_name
from project_runtime_client.infrastructure.workspace_roots import _DIR_FLAGS as _DIR_FLAGS
from project_runtime_client.infrastructure.workspace_roots import _OPENAT2_X86_64 as _OPENAT2_X86_64
from project_runtime_client.infrastructure.workspace_roots import (
    _RESOLVE_BENEATH as _RESOLVE_BENEATH,
)
from project_runtime_client.infrastructure.workspace_roots import (
    _RESOLVE_NO_SYMLINKS as _RESOLVE_NO_SYMLINKS,
)
from project_runtime_client.infrastructure.workspace_roots import (
    _RESOLVE_NO_XDEV as _RESOLVE_NO_XDEV,
)
from project_runtime_client.infrastructure.workspace_roots import (
    ProjectRootRegistry as ProjectRootRegistry,
)
from project_runtime_client.infrastructure.workspace_roots import _open_beneath as _open_beneath
from project_runtime_client.infrastructure.workspace_roots import _OpenHow as _OpenHow
from project_runtime_client.infrastructure.workspace_roots import _safe_ancestor as _safe_ancestor
from project_runtime_client.infrastructure.workspace_roots import _safe_directory as _safe_directory
