"""Signed authority precedes egress; Files owns the durable write."""

from collections.abc import AsyncIterator
from typing import Protocol

from project_runtime_client.domain.authorization import ProjectInvocation
from web_runtime.domain.public_download import DownloadProgress, DownloadRejected, PublicDownload


class DownloadResponse(Protocol):
    def content_lengths(self) -> tuple[str, ...]: ...
    async def read(self, size: int) -> bytes: ...
    async def close(self) -> None: ...


class DownloadTransport(Protocol):
    async def open(self, url: str) -> DownloadResponse: ...


class DownloadClock(Protocol):
    def now(self) -> float: ...


class DownloadDestination[Result](Protocol):
    def require_write_ready(self) -> None: ...
    async def require_authority(self, invocation: ProjectInvocation) -> None: ...
    async def write(
        self,
        invocation: ProjectInvocation,
        destination: str,
        chunks: AsyncIterator[bytes],
        specification: PublicDownload,
    ) -> Result: ...


class DownloadToFiles[Result]:
    def __init__(
        self,
        destination: DownloadDestination[Result],
        transport: DownloadTransport,
        clock: DownloadClock,
    ) -> None:
        self.destination = destination
        self.transport = transport
        self.clock = clock

    @staticmethod
    def require_scope(invocation: ProjectInvocation, specification: PublicDownload) -> None:
        scope = invocation.operation_scope
        if (
            scope is None
            or scope.action != "files.write"
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
            or scope.request_uuid != specification.operation_uuid
        ):
            raise DownloadRejected("PROJECT_FILES_SIGNED_OPERATION_REQUIRED")

    async def execute(
        self,
        invocation: ProjectInvocation,
        url: str,
        destination: str,
        specification: PublicDownload,
    ) -> Result:
        self.require_scope(invocation, specification)
        self.destination.require_write_ready()
        await self.destination.require_authority(invocation)
        deadline = self.clock.now() + specification.max_seconds
        try:
            response = await self.transport.open(url)
        except Exception as exc:
            raise DownloadRejected("PROJECT_HTTP_EGRESS_UNAVAILABLE") from exc
        try:
            specification.require_content_length(response.content_lengths())
            progress = DownloadProgress(specification, deadline)
            return await self.destination.write(
                invocation,
                destination,
                self._chunks(response, progress),
                specification,
            )
        finally:
            await response.close()

    async def _chunks(
        self,
        response: DownloadResponse,
        progress: DownloadProgress,
    ) -> AsyncIterator[bytes]:
        while True:
            progress.require_time(self.clock.now())
            piece = await response.read(progress.specification.chunk_bytes)
            progress.require_time(self.clock.now())
            if not piece:
                break
            progress.accept(piece)
            yield piece
        progress.finish()
