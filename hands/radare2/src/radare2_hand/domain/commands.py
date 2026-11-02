"""Only fixed native analysis commands and bounded numeric selectors are admitted."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .binaries import address, bounded_int

type NativeTool = Literal[
    "radare2_binary_info",
    "radare2_functions",
    "radare2_strings",
    "radare2_disassemble",
    "radare2_xrefs",
]


@dataclass(frozen=True, slots=True)
class StartUpload:
    name: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class UploadChunk:
    upload_id: UUID
    offset: int
    content_base64: str


@dataclass(frozen=True, slots=True)
class FinishUpload:
    upload_id: UUID


@dataclass(frozen=True, slots=True)
class AbortUpload:
    upload_id: UUID


@dataclass(frozen=True, slots=True)
class ListBinaries:
    pass


@dataclass(frozen=True, slots=True)
class DeleteBinary:
    binary_id: UUID


@dataclass(slots=True)
class NativeDeadline:
    expires_at: int | None = 0


@dataclass(frozen=True, slots=True)
class NativeCommand:
    binary_id: UUID
    command: str
    page: tuple[int, int] | None = None


type AnalyzerCommand = (
    StartUpload
    | UploadChunk
    | FinishUpload
    | AbortUpload
    | ListBinaries
    | DeleteBinary
    | NativeCommand
)


def native_command(
    name: NativeTool,
    binary: UUID,
    *,
    location: str = "0x0",
    count: int = 32,
    offset: int = 0,
    limit: int = 100,
) -> NativeCommand:
    if name == "radare2_disassemble":
        count = bounded_int(count, 1, 256)
        return NativeCommand(binary, f"pdj {count} @ {address(location)}")
    if name == "radare2_xrefs":
        return NativeCommand(binary, f"aa;axtj @ {address(location)}")
    if name == "radare2_binary_info":
        return NativeCommand(binary, "ij")
    if name not in {"radare2_functions", "radare2_strings"}:
        raise ValueError("Unknown static analysis tool")
    offset = bounded_int(offset, 0, 1_000_000)
    limit = bounded_int(limit, 1, 500)
    command = "aa;aflj" if name == "radare2_functions" else "izj"
    return NativeCommand(binary, command, (offset, limit))
