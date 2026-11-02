"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

import time as time
from collections.abc import Iterator as Iterator
from contextlib import contextmanager as contextmanager
from dataclasses import dataclass as dataclass

from modules.files._attachment_transport import PinnedAttachmentResponse as PinnedAttachmentResponse
from modules.files._attachment_transport import open_public_attachment as open_public_attachment
from modules.files.application.ingest_attachment import AttachmentBody as AttachmentBody
from modules.files.workspace_store import WorkspaceFileError as WorkspaceFileError
from project_runtime_client.files.infrastructure.attachment_transport import (
    PublicAttachmentBody as PublicAttachmentBody,
)
from project_runtime_client.files.infrastructure.attachment_transport import (
    _CompositionPublicAttachmentTransport as _SharedPublicAttachmentTransport,
)


class PublicAttachmentTransport(_SharedPublicAttachmentTransport):
    """Keep the local attachment provider and transport type."""

    _open_attachment = staticmethod(open_public_attachment)
