"""Prepare a confined destination, validate its append position, then write."""

from dataclasses import dataclass
from typing import Protocol

from project_runtime_client.workspace_compat.domain.receipts import WorkspaceWrite
from project_runtime_client.workspace_compat.domain.transfers import WorkspaceAppendPlan


class WorkspaceChunkTarget(Protocol):
    def size(self) -> int: ...

    def append(self, data: bytes, *, truncate: bool) -> None: ...

    def relative_path(self) -> str: ...


class WorkspaceChunkStorage(Protocol):
    def prepare_chunk(self, path: str, *, create_parents: bool) -> WorkspaceChunkTarget: ...


@dataclass(frozen=True, slots=True)
class WorkspaceChunkCommand:
    path: str
    data: bytes
    offset: int
    truncate: bool
    create_parents: bool
    max_file_bytes: int


@dataclass(frozen=True, slots=True)
class AppendWorkspaceChunk:
    storage: WorkspaceChunkStorage
    plan: type[WorkspaceAppendPlan]

    def execute(self, command: WorkspaceChunkCommand) -> WorkspaceWrite:
        target = self.storage.prepare_chunk(command.path, create_parents=command.create_parents)
        plan = self.plan.prepare(
            current_size=target.size(),
            byte_count=len(command.data),
            offset=command.offset,
            truncate=command.truncate,
            max_file_bytes=command.max_file_bytes,
        )
        target.append(command.data, truncate=command.truncate)
        return WorkspaceWrite(
            target.relative_path(), len(command.data), plan.next_offset, plan.next_offset
        )


class _BoundAppendWorkspaceChunk(AppendWorkspaceChunk):
    _plan_factory: type[WorkspaceAppendPlan]

    def __init__(self, storage: WorkspaceChunkStorage) -> None:
        super().__init__(storage, self._plan_factory)
