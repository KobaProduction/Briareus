"""Bounded monotonic download window over the SSRF-aware HTTPS source."""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from project_runtime_client.files.application.ingest_attachment import AttachmentBody
from project_runtime_client.files.infrastructure.public_attachment import PinnedAttachmentResponse
from project_runtime_client.workspace_compat.domain.transfers import WorkspaceFileError


@dataclass(frozen=True)
class PublicAttachmentBody:
    response: PinnedAttachmentResponse
    deadline: float

    @property
    def declared_size(self) -> int | None:
        lengths = self.response.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            raise WorkspaceFileError("attachment returned conflicting Content-Length")
        if not lengths:
            return None
        try:
            return int(lengths[0])
        except ValueError as exc:
            raise WorkspaceFileError("attachment returned invalid Content-Length") from exc

    def read(self) -> bytes:
        if time.monotonic() >= self.deadline:
            raise WorkspaceFileError("attachment download time limit exceeded")
        chunk = self.response.read(1024 * 1024)
        if time.monotonic() >= self.deadline:
            raise WorkspaceFileError("attachment download time limit exceeded")
        return chunk


class PublicAttachmentTransport(ABC):
    def __init__(self, deadline: float) -> None:
        self._deadline = deadline

    @abstractmethod
    def _open_response(self, url: str) -> PinnedAttachmentResponse:
        raise NotImplementedError

    @contextmanager
    def open(self, url: str) -> Iterator[AttachmentBody]:
        try:
            response = self._open_response(url)
        except Exception as exc:
            if isinstance(exc, WorkspaceFileError):
                raise
            raise WorkspaceFileError(f"attachment download failed: {type(exc).__name__}") from exc
        with response:
            yield PublicAttachmentBody(response, self._deadline)


class _CompositionPublicAttachmentTransport(PublicAttachmentTransport):
    _open_attachment: Callable[[str], PinnedAttachmentResponse]

    def _open_response(self, url: str) -> PinnedAttachmentResponse:
        return self._open_attachment(url)
