"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

from dataclasses import dataclass as dataclass

from project_runtime_client.files.domain.attachment import (
    AttachmentExpectation as AttachmentExpectation,
)
from project_runtime_client.files.domain.attachment import AttachmentRejected as AttachmentRejected
from project_runtime_client.files.domain.attachment import normalize_sha256 as normalize_sha256
