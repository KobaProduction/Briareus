"""Composition root for private binary import, integrity checks, and fixed native analysis."""

import asyncio
import time
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from mcp.types import CallToolResult

from .application.imports import (
    BinaryDeleted,
    BinaryImports,
    BinaryListing,
    BinaryReceipt,
    ChunkReceipt,
    ImportResult,
    PendingUpload,
    UploadAborted,
)
from .application.inspection import InspectBinary
from .domain.binaries import (
    MAX_BINARY,
    MAX_CHUNK,
    MAX_ENTRIES,
    MAX_OUTPUT,
    MAX_STORAGE,
    R2_VERSION,
    address,
    bounded_int,
    decode_chunk,
    identifier,
)
from .domain.commands import (
    AbortUpload,
    AnalyzerCommand,
    DeleteBinary,
    FinishUpload,
    ListBinaries,
    NativeCommand,
    StartUpload,
    UploadChunk,
)
from .infrastructure.binary_storage import BinaryFiles, read_private
from .infrastructure.native_inspection import NativeInspection
from .infrastructure.native_process import NativeProcesses
from .presentation import native_result

__all__ = [
    "MAX_BINARY",
    "MAX_CHUNK",
    "MAX_ENTRIES",
    "MAX_OUTPUT",
    "MAX_STORAGE",
    "R2_VERSION",
    "Analyzer",
    "address",
    "bounded_int",
    "decode_chunk",
    "identifier",
]

type AnalyzerResult = ImportResult | CallToolResult


class ExecutionDeadline(Protocol):
    @property
    def expires_at(self) -> float | None: ...


class Analyzer:
    def __init__(self, root: Path, *, executable: str = "/usr/local/bin/radare2") -> None:
        self.root = root
        self.lock = asyncio.Lock()
        self.storage = BinaryFiles(root)
        self.native_process = NativeProcesses(executable)
        self.imports = BinaryImports(self.storage, self.lock, uuid4, lambda: int(time.time()))
        self.inspection = NativeInspection(
            InspectBinary(self.storage), self.native_process, self.lock
        )

    @property
    def executable(self) -> str:
        return self.native_process.executable

    @executable.setter
    def executable(self, executable: str) -> None:
        self.native_process.executable = executable

    @property
    def processes(self) -> set[asyncio.subprocess.Process]:
        return self.native_process.processes

    @property
    def ready(self) -> bool:
        return self.native_process.ready

    @staticmethod
    def _read(path: Path, maximum: int) -> bytes:
        return read_private(path, maximum)

    async def start(self, name: str, sha256: str, size: int) -> PendingUpload:
        return await self.imports.start(name, sha256, size)

    async def chunk(self, upload_id: UUID, offset: int, content_base64: str) -> ChunkReceipt:
        return await self.imports.chunk(upload_id, offset, content_base64)

    async def finish(self, upload_id: UUID) -> BinaryReceipt:
        return await self.imports.finish(upload_id)

    async def abort(self, upload_id: UUID) -> UploadAborted:
        return await self.imports.abort(upload_id)

    async def listing(self) -> BinaryListing:
        return await self.imports.listing()

    async def delete(self, binary_id: UUID) -> BinaryDeleted:
        return await self.imports.delete(binary_id)

    async def native(self, binary_id: UUID, command: str, deadline: float | None) -> bytes:
        return await self.inspection.invoke(NativeCommand(binary_id, command), deadline)

    async def _run(self, arguments: list[str], deadline: float | None) -> bytes:
        return await self.native_process.run(arguments, deadline)

    async def startup(self) -> None:
        await self.native_process.startup()

    async def close(self) -> None:
        await self.native_process.close()

    async def execute(
        self,
        command: AnalyzerCommand,
        permit: ExecutionDeadline,
    ) -> AnalyzerResult:
        if isinstance(command, NativeCommand):
            return native_result(command, await self.inspection.invoke(command, permit.expires_at))
        return await self.import_command(command)

    async def import_command(
        self,
        command: StartUpload
        | UploadChunk
        | FinishUpload
        | AbortUpload
        | ListBinaries
        | DeleteBinary,
    ) -> ImportResult:
        if isinstance(command, StartUpload):
            return await self.start(command.name, command.sha256, command.size)
        if isinstance(command, ListBinaries):
            return await self.listing()
        if isinstance(command, DeleteBinary):
            return await self.delete(command.binary_id)
        if isinstance(command, FinishUpload):
            return await self.finish(command.upload_id)
        if isinstance(command, AbortUpload):
            return await self.abort(command.upload_id)
        return await self.chunk(
            command.upload_id,
            command.offset,
            command.content_base64,
        )
