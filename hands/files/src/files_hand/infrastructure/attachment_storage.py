"""Public HTTPS attachment source and descriptor-confined staging adapter."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from files_hand.application.ingest_attachment import AttachmentBody, AttachmentStage
from files_hand.infrastructure.chunk_storage import DescriptorWorkspace
from modules.files._attachment_transport import PinnedAttachmentResponse, open_public_attachment


@dataclass
class PublicAttachmentBody:
    response: PinnedAttachmentResponse
    workspace: DescriptorWorkspace

    @property
    def declared_size(self) -> int | None:
        lengths = self.response.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            raise ValueError("Conflicting attachment length")
        return int(lengths[0]) if lengths else None

    def read(self) -> bytes:
        self.workspace.check()
        data = self.response.read(1024 * 1024)
        self.workspace.check()
        return data


@dataclass
class DescriptorAttachmentStage:
    workspace: DescriptorWorkspace
    parent: int
    temporary: str
    name: str
    fd: int
    overwrite: bool

    def write(self, data: bytes) -> None:
        self.workspace.write_bytes(self.fd, data)

    def commit(self) -> None:
        os.fsync(self.fd)
        self.workspace.commit(self.parent, self.temporary, self.name, overwrite=self.overwrite)


class WorkspaceAttachmentStorage:
    def __init__(self, workspace: DescriptorWorkspace, deadline: float) -> None:
        self._workspace, self._deadline = workspace, deadline

    @contextmanager
    def stage(self, destination: str, overwrite: bool) -> Iterator[AttachmentStage]:
        with (
            self._workspace.parent(destination, create=True) as (parent, name),
            self._workspace.staged(parent) as (temporary, fd),
        ):
            if self._workspace.existing(parent, name) is not None and not overwrite:
                raise ValueError("Attachment destination exists")
            yield DescriptorAttachmentStage(self._workspace, parent, temporary, name, fd, overwrite)

    @contextmanager
    def open(self, url: str) -> Iterator[AttachmentBody]:
        with open_public_attachment(url, deadline=self._deadline) as response:
            yield PublicAttachmentBody(response, self._workspace)
