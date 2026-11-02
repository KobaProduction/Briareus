"""Unmounted Briareus Web→Files transfer and protected Browser trust gate.

All Project file effects require the exact signed A6 FilesQuota-v2 operation.
No R6 local browser lease, global profile, inherited process environment or
external user's Chrome process is adopted as a trusted RuntimeSession owner.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from project_runtime_client.authorization import (
    ProjectInvocation,
    ProjectRuntimeAuthority,
)
from project_runtime_client.domain._code_error import _CodeError
from project_runtime_client.files.workspace import ProjectFileEntry
from web_runtime.application.public_download import (
    DownloadClock,
    DownloadDestination,
    DownloadToFiles,
    DownloadTransport,
)
from web_runtime.domain.public_download import DownloadRejected, PublicDownload


@dataclass(frozen=True, slots=True)
class IsolatedBrowserProfile:
    """Trusted factory attestation, not proof of OS isolation by itself.

    The injected `InternalBrowserFactory` must be an approved browser process
    manager before this unmounted adapter is ever enabled. A shared Browser
    profile, cookie jar, downloads folder or cache is not a Project sandbox.
    """

    project_id: UUID
    context_uuid: UUID
    profile_uuid: UUID
    profile_isolated: bool
    cookies_isolated: bool
    cache_isolated: bool
    downloads_project_scoped: bool
    host_browser_unmodified: bool


@dataclass(frozen=True, slots=True)
class RemoteBrowserAttachment:
    """User-owned Chrome: consent and connection identity, NEVER process kill."""

    project_id: UUID
    attachment_uuid: UUID
    consent_verified: bool
    operator_browser_owned: bool
    process_termination_forbidden: bool


class InternalProjectBrowser(Protocol):
    """Owns one Project's private Chromium context/profile, not a shared tab."""

    project_id: UUID
    context_uuid: UUID
    isolation: IsolatedBrowserProfile

    async def close_owned_context(self) -> None: ...


class InternalBrowserFactory(Protocol):
    async def open_isolated(self, *, project_id: UUID) -> InternalProjectBrowser: ...


class RemoteProjectBrowser(Protocol):
    """An attached external user's Chrome; never destroy its native process."""

    project_id: UUID
    attachment_uuid: UUID
    ownership: RemoteBrowserAttachment

    async def disconnect(self) -> None: ...


class RemoteBrowserConnector(Protocol):
    async def attach(self, *, project_id: UUID) -> RemoteProjectBrowser: ...


class ProjectWebRuntimeUnavailable(_CodeError):
    pass


class WebFilesPort(Protocol):
    @property
    def max_file_bytes(self) -> int: ...

    async def write(
        self,
        invocation: ProjectInvocation,
        destination: str,
        content: bytes,
        *,
        overwrite: bool,
        create_parents: bool,
        operation_uuid: UUID,
    ) -> ProjectFileEntry: ...

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


class DownloadWorkflowFactory(Protocol):
    def __call__(self) -> DownloadToFiles[ProjectFileEntry]: ...


class ProjectWebRuntime:
    """Stateless external HTTPS transfer, no Browser OS/process ownership."""

    def __init__(
        self,
        *,
        authority: ProjectRuntimeAuthority,
        files: WebFilesPort,
        download_factory: DownloadWorkflowFactory,
    ) -> None:
        self.authority = authority
        self.files = files
        self._download_factory = download_factory

    async def require_browser_owner(
        self,
        invocation: ProjectInvocation,
        *,
        mode: Literal["managed", "remote"],
    ) -> None:
        if mode not in {"managed", "remote"}:
            raise ProjectWebRuntimeUnavailable("PROJECT_BROWSER_MODE_INVALID")
        await self.authority.require(
            invocation, "web.internal" if mode == "managed" else "web.remote"
        )
        # A9 has not accepted the signed owner nonce. An internal Chromium
        # needs an attested Project-only UID/mount/profile/cgroup worker; a
        # remote user Chrome needs a verified consent-bound transport owner.
        # Neither can use an in-memory R6 lease or global CDP/browser profile.
        raise ProjectWebRuntimeUnavailable("PROJECT_BROWSER_SIGNED_OWNER_UNAVAILABLE")

    async def download_public_https(
        self,
        invocation: ProjectInvocation,
        *,
        url: str,
        destination: str,
        expected_size: int,
        expected_sha256: str,
        operation_uuid: UUID,
        max_seconds: float = 600.0,
        chunk_bytes: int = 65536,
    ) -> ProjectFileEntry:
        """Public pinned HTTPS into A6 Files, using one durable write UUID.

        This is not an HTTP/MCP route. A separate signed Files service+human
        proof must validate each quota/dispatch/storage/commit effect; no
        credential-bearing HTTP response or proxy URL is forwarded to Files.
        """
        try:
            specification = PublicDownload(
                expected_size,
                expected_sha256,
                operation_uuid,
                max_seconds,
                chunk_bytes,
                self.files.max_file_bytes,
            )
            workflow = self._download_factory()
            return await workflow.execute(invocation, url, destination, specification)
        except DownloadRejected as exc:
            raise ProjectWebRuntimeUnavailable(str(exc)) from exc

    async def save_http_download(
        self,
        invocation: ProjectInvocation,
        destination: str,
        content: bytes,
        *,
        operation_uuid: UUID,
    ) -> ProjectFileEntry:
        """Selected bounded content is still an independently signed write."""
        return await self.files.write(
            invocation,
            destination,
            content,
            overwrite=False,
            create_parents=False,
            operation_uuid=operation_uuid,
        )

    async def save_http_download_stream(
        self,
        invocation: ProjectInvocation,
        destination: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        expected_sha256: str,
        operation_uuid: UUID,
    ) -> ProjectFileEntry:
        """No speculative byte size, idempotency fallback or raw key env."""
        return await self.files.write_stream(
            invocation,
            destination,
            chunks,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            operation_uuid=operation_uuid,
        )


class _CompositionProjectWebRuntime[FilesT: WebFilesPort](ProjectWebRuntime):
    files: FilesT
    _destination_type: Callable[
        [FilesT, ProjectRuntimeAuthority], DownloadDestination[ProjectFileEntry]
    ]
    _transport_type: Callable[[], DownloadTransport]
    _clock_type: Callable[[], DownloadClock]

    def __init__(self, *, authority: ProjectRuntimeAuthority, files: FilesT) -> None:
        def download_factory() -> DownloadToFiles[ProjectFileEntry]:
            return DownloadToFiles(
                self._destination_type(self.files, self.authority),
                self._transport_type(),
                self._clock_type(),
            )

        super().__init__(authority=authority, files=files, download_factory=download_factory)
