"""Compatibility API for the canonical shared Files client implementation."""

import ctypes as ctypes
import errno as errno
import fcntl as fcntl
import hashlib as hashlib
import os as os
import re as re
import stat as stat
import time as time
from collections.abc import Iterator as Iterator
from contextlib import contextmanager as contextmanager
from contextlib import suppress as suppress
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from uuid import UUID as UUID
from uuid import uuid4 as uuid4

from modules.project_runtime import ProjectAction as ProjectAction
from modules.project_runtime import ProjectPermit as ProjectPermit
from modules.project_runtime.authorization import ProjectOwnerFence as ProjectOwnerFence
from modules.project_runtime.workspace_roots import _DIR_FLAGS as _DIR_FLAGS
from modules.project_runtime.workspace_roots import ProjectFileError as ProjectFileError
from modules.project_runtime.workspace_roots import ProjectRootRegistry as ProjectRootRegistry
from modules.project_runtime.workspace_roots import _open_beneath as _open_beneath
from modules.project_runtime.workspace_roots import _safe_directory as _safe_directory
from project_runtime_client.files.workspace import _FILE_FLAGS as _FILE_FLAGS
from project_runtime_client.files.workspace import _RENAME_NOREPLACE as _RENAME_NOREPLACE
from project_runtime_client.files.workspace import _TEMP_NAME as _TEMP_NAME
from project_runtime_client.files.workspace import ProjectFileEntry as ProjectFileEntry
from project_runtime_client.files.workspace import ProjectFilePage as ProjectFilePage
from project_runtime_client.files.workspace import ProjectFileSnapshot as ProjectFileSnapshot
from project_runtime_client.files.workspace import ProjectFileWriteStage as ProjectFileWriteStage
from project_runtime_client.files.workspace import ProjectWorkspaceFiles as ProjectWorkspaceFiles
from project_runtime_client.files.workspace import SnapshotBytes as SnapshotBytes
from project_runtime_client.files.workspace import _checked_entry as _checked_entry
from project_runtime_client.files.workspace import _checked_file as _checked_file
from project_runtime_client.files.workspace import _components as _components
from project_runtime_client.files.workspace import _copy_snapshot as _copy_snapshot
from project_runtime_client.files.workspace import _leaf_stat as _leaf_stat
from project_runtime_client.files.workspace import _open_snapshot_inode as _open_snapshot_inode
from project_runtime_client.files.workspace import _remove_orphan_stage as _remove_orphan_stage
from project_runtime_client.files.workspace import _rename_no_replace as _rename_no_replace

from .domain.file_entries import FileEntryKind as FileEntryKind
