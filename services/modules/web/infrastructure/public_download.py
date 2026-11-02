"""Pinned HTTPS and cancellation-safe Files adapters."""

import time as time
from collections.abc import AsyncIterator as AsyncIterator
from dataclasses import dataclass as dataclass

from modules.files._attachment_transport import PinnedAttachmentResponse as PinnedAttachmentResponse
from modules.files._attachment_transport import open_public_attachment
from modules.files.project_files import ProjectFilesService
from modules.files.project_files import _drain_cancellable_file_io as _drain_cancellable_file_io
from modules.files.project_workspace import ProjectFileEntry as ProjectFileEntry
from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from modules.web.domain.public_download import PublicDownload as PublicDownload
from web_runtime.infrastructure.public_download import (
    MonotonicDownloadClock as _SharedMonotonicDownloadClock,
)
from web_runtime.infrastructure.public_download import (
    PinnedDownloadResponse as _SharedPinnedDownloadResponse,
)
from web_runtime.infrastructure.public_download import (
    PinnedDownloadTransport as _SharedPinnedDownloadTransport,
)
from web_runtime.infrastructure.public_download import (
    SignedFilesDestination as _SharedSignedFilesDestination,
)


class PinnedDownloadResponse(_SharedPinnedDownloadResponse):
    __slots__ = ()


class PinnedDownloadTransport(_SharedPinnedDownloadTransport[PinnedDownloadResponse]):
    _response_type = PinnedDownloadResponse
    _open_attachment = staticmethod(open_public_attachment)


class MonotonicDownloadClock(_SharedMonotonicDownloadClock):
    """Keep this adapter's nominal clock type."""


class SignedFilesDestination(_SharedSignedFilesDestination[ProjectFilesService]):
    __slots__ = ()
