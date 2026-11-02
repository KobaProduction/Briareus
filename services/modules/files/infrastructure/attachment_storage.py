"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

import os as os
import uuid as uuid
from collections.abc import Iterator as Iterator
from contextlib import contextmanager as contextmanager
from contextlib import suppress as suppress
from dataclasses import dataclass as dataclass
from pathlib import Path as Path
from typing import BinaryIO as BinaryIO

from modules.files.application.ingest_attachment import AttachmentSink as AttachmentSink
from modules.files.application.ingest_attachment import AttachmentTarget as AttachmentTarget
from modules.files.project_workspace import _rename_no_replace as _rename_no_replace
from modules.files.receipts import WorkspaceIngestReceipt as WorkspaceIngestReceipt
from modules.files.workspace_store import WorkspaceFileError as WorkspaceFileError
from modules.files.workspace_store import WorkspaceFileStore as WorkspaceFileStore
from modules.project_runtime.workspace_roots import ProjectFileError as ProjectFileError
from modules.workspace_compat.domain.receipts import WorkspaceFileEntry as WorkspaceFileEntry
from project_runtime_client.files.infrastructure.attachment_storage import (
    BufferedAttachmentSink as BufferedAttachmentSink,
)
from project_runtime_client.files.infrastructure.attachment_storage import (
    PinnedAttachmentTarget as PinnedAttachmentTarget,
)
from project_runtime_client.files.infrastructure.attachment_storage import (
    WorkspaceAttachmentStorage as WorkspaceAttachmentStorage,
)
from project_runtime_client.files.infrastructure.attachment_storage import (
    pinned_parent as pinned_parent,
)
