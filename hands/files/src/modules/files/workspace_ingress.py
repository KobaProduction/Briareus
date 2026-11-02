"""Legacy Files upload composition over typed transfer ports."""

from __future__ import annotations

import time as time

from files_hand.presentation.workspace_ingress import _validate_sha256 as _validate_sha256
from files_hand.presentation.workspace_ingress import ingest_workspace_file as ingest_workspace_file

from common.models import validated_call as validated_call
from modules.files.application.ingest_attachment import IngestAttachment as IngestAttachment
from modules.files.domain.attachment import (
    AttachmentExpectation as AttachmentExpectation,
)
from modules.files.domain.attachment import (
    AttachmentRejected as AttachmentRejected,
)
from modules.files.domain.attachment import (
    normalize_sha256 as normalize_sha256,
)
from modules.files.receipts import WorkspaceIngestReceipt as WorkspaceIngestReceipt

from ._attachment_transport import validate_public_attachment_url as validate_public_attachment_url
from .models import ClientFile as ClientFile
from .workspace_store import WorkspaceFileError as WorkspaceFileError
from .workspace_store import WorkspaceFileStore as WorkspaceFileStore

