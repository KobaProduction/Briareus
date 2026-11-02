"""Compatibility API for the bounded Web runtime implementation."""

from collections.abc import AsyncIterator as AsyncIterator
from typing import Protocol as Protocol

from modules.project_runtime.domain.authorization import ProjectInvocation as ProjectInvocation
from modules.web.domain.public_download import DownloadProgress as DownloadProgress
from modules.web.domain.public_download import DownloadRejected as DownloadRejected
from modules.web.domain.public_download import PublicDownload as PublicDownload
from web_runtime.application.public_download import DownloadClock as DownloadClock
from web_runtime.application.public_download import DownloadDestination as DownloadDestination
from web_runtime.application.public_download import DownloadResponse as DownloadResponse
from web_runtime.application.public_download import DownloadToFiles as DownloadToFiles
from web_runtime.application.public_download import DownloadTransport as DownloadTransport
