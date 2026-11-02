"""Compatibility API for the bounded Web runtime implementation."""

from collections.abc import AsyncIterator as AsyncIterator
from dataclasses import dataclass as dataclass
from typing import Literal as Literal
from typing import Protocol as Protocol
from uuid import UUID as UUID

from modules.files.project_files import ProjectFilesService as ProjectFilesService
from modules.files.project_workspace import ProjectFileEntry as ProjectFileEntry
from modules.project_runtime import ProjectInvocation as ProjectInvocation
from modules.project_runtime import ProjectRuntimeAuthority as ProjectRuntimeAuthority
from modules.web.application.public_download import DownloadToFiles as DownloadToFiles
from modules.web.domain.public_download import DownloadRejected as DownloadRejected
from modules.web.domain.public_download import PublicDownload as PublicDownload
from modules.web.infrastructure.public_download import (
    MonotonicDownloadClock as MonotonicDownloadClock,
)
from modules.web.infrastructure.public_download import (
    PinnedDownloadTransport as PinnedDownloadTransport,
)
from modules.web.infrastructure.public_download import (
    SignedFilesDestination as SignedFilesDestination,
)
from web_runtime.project_runtime import InternalBrowserFactory as InternalBrowserFactory
from web_runtime.project_runtime import InternalProjectBrowser as InternalProjectBrowser
from web_runtime.project_runtime import IsolatedBrowserProfile as IsolatedBrowserProfile
from web_runtime.project_runtime import ProjectWebRuntimeUnavailable as ProjectWebRuntimeUnavailable
from web_runtime.project_runtime import RemoteBrowserAttachment as RemoteBrowserAttachment
from web_runtime.project_runtime import RemoteBrowserConnector as RemoteBrowserConnector
from web_runtime.project_runtime import RemoteProjectBrowser as RemoteProjectBrowser
from web_runtime.project_runtime import _CompositionProjectWebRuntime as _ProjectWebRuntime


class ProjectWebRuntime(_ProjectWebRuntime[ProjectFilesService]):
    """Keep the local Files type and audited Web download composition."""

    _destination_type = SignedFilesDestination
    _transport_type = PinnedDownloadTransport
    _clock_type = MonotonicDownloadClock
