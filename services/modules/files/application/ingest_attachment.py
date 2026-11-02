"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

import hashlib as hashlib
from contextlib import AbstractContextManager as AbstractContextManager
from typing import Protocol as Protocol

from modules.files.domain.attachment import AttachmentExpectation as AttachmentExpectation
from modules.files.receipts import WorkspaceIngestReceipt as WorkspaceIngestReceipt
from project_runtime_client.files.application.ingest_attachment import (
    AttachmentBody as AttachmentBody,
)
from project_runtime_client.files.application.ingest_attachment import (
    AttachmentSink as AttachmentSink,
)
from project_runtime_client.files.application.ingest_attachment import (
    AttachmentStorage as AttachmentStorage,
)
from project_runtime_client.files.application.ingest_attachment import (
    AttachmentTarget as AttachmentTarget,
)
from project_runtime_client.files.application.ingest_attachment import (
    AttachmentTransport as AttachmentTransport,
)
from project_runtime_client.files.application.ingest_attachment import (
    IngestAttachment as IngestAttachment,
)
