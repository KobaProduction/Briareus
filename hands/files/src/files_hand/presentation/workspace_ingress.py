"""Legacy Files upload composition over typed transfer ports."""

from __future__ import annotations

import time

from common.models import validated_call
from modules.files._attachment_transport import validate_public_attachment_url
from modules.files.application.ingest_attachment import IngestAttachment
from modules.files.domain.attachment import (
    AttachmentExpectation,
    AttachmentRejected,
    normalize_sha256,
)
from modules.files.models import ClientFile
from modules.files.receipts import WorkspaceIngestReceipt
from modules.files.workspace_store import WorkspaceFileError, WorkspaceFileStore


def _validate_sha256(value: str) -> str:
    try:
        return normalize_sha256(value)
    except AttachmentRejected as exc:
        raise WorkspaceFileError(str(exc)) from exc


@validated_call
def ingest_workspace_file(
    file: ClientFile,
    destination: str,
    expected_size: int | None = None,
    expected_sha256: str = "",
    overwrite: bool = False,
    *,
    workspace: WorkspaceFileStore,
    max_bytes: int,
) -> WorkspaceIngestReceipt:
    from modules.files.infrastructure.attachment_storage import WorkspaceAttachmentStorage
    from modules.files.infrastructure.attachment_transport import PublicAttachmentTransport

    download_url = file.download_url.strip()
    validate_public_attachment_url(download_url)
    expected_digest = _validate_sha256(expected_sha256)
    try:
        expected = AttachmentExpectation(max_bytes, expected_size, expected_digest)
        target = workspace.target_path(destination)
        if target.exists() and not overwrite:
            raise WorkspaceFileError(f"destination already exists: {destination}")
        deadline = time.monotonic() + 600.0
        return IngestAttachment(
            WorkspaceAttachmentStorage(workspace, target),
            PublicAttachmentTransport(deadline),
        ).execute(download_url, destination, overwrite, expected)
    except AttachmentRejected as exc:
        raise WorkspaceFileError(str(exc)) from exc
