"""Web-owned pinned HTTPS and cancellation-safe Files adapters."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from project_runtime_client.authorization import ProjectInvocation, ProjectRuntimeAuthority
from project_runtime_client.files.infrastructure.public_attachment import PinnedAttachmentResponse
from project_runtime_client.files.service import _drain_cancellable_file_io
from project_runtime_client.files.signed import A6SignedFilesFlow
from project_runtime_client.files.workspace import ProjectFileEntry
from web_runtime.application.public_download import DownloadResponse
from web_runtime.domain.public_download import PublicDownload


class SignedFilesPort(Protocol):
    @property
    def a6_quota(self) -> A6SignedFilesFlow: ...

    async def write_stream(
        self,
        invocation: ProjectInvocation,
        destination: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        expected_sha256: str,
        operation_uuid: UUID,
    ) -> ProjectFileEntry: ...


@dataclass(slots=True)
class PinnedDownloadResponse:
    response: PinnedAttachmentResponse

    def content_lengths(self) -> tuple[str, ...]:
        return tuple(self.response.headers.get_all("Content-Length", []))

    async def read(self, size: int) -> bytes:
        return await _drain_cancellable_file_io(self.response.read, size)

    async def close(self) -> None:
        await _drain_cancellable_file_io(self.response.__exit__, None, None, None)


class PinnedDownloadTransport[ResponseT: DownloadResponse]:
    _response_type: Callable[[PinnedAttachmentResponse], ResponseT]
    _open_attachment: Callable[[str], PinnedAttachmentResponse]

    async def open(self, url: str) -> ResponseT:
        return self._response_type(await _drain_cancellable_file_io(self._open_attachment, url))


class MonotonicDownloadClock:
    def now(self) -> float:
        return time.monotonic()


@dataclass(slots=True)
class SignedFilesDestination[FilesT: SignedFilesPort]:
    files: FilesT
    authority: ProjectRuntimeAuthority

    def require_write_ready(self) -> None:
        self.files.a6_quota.require_write_ready()

    async def require_authority(self, invocation: ProjectInvocation) -> None:
        await self.authority.require(invocation, "files.write")

    async def write(
        self,
        invocation: ProjectInvocation,
        destination: str,
        chunks: AsyncIterator[bytes],
        specification: PublicDownload,
    ) -> ProjectFileEntry:
        return await self.files.write_stream(
            invocation,
            destination,
            chunks,
            expected_size=specification.expected_size,
            expected_sha256=specification.expected_sha256,
            operation_uuid=specification.operation_uuid,
        )
