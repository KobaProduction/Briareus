"""The minimum private Files runtime's path and read budgets."""

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from .chunk_write import FileSnapshot


def project_components(path: str) -> tuple[str, ...]:
    if (
        len(path.encode("utf-8")) > 4096
        or not unicodedata.is_normalized("NFC", path)
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
    ):
        raise ValueError("Canonical relative path required")
    parts = tuple(path.split("/")) if path else ()
    if len(parts) > 64 or any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise ValueError("Path must stay beneath the project root")
    return parts


def require_private_file(before: FileSnapshot) -> None:
    if not before.regular or before.size_bytes > 262_144:
        raise ValueError("Bounded regular file required")


def require_private_directory_index(index: int) -> None:
    if index >= 1000:
        raise ValueError("Directory exceeds minimum-runtime listing budget")


@dataclass(frozen=True, slots=True)
class ConfinedEntry:
    device: int
    uid: int
    mode: int
    regular: bool
    directory: bool
    links: int

    def require_safe(self, root_device: int, execution_uid: int) -> None:
        if (
            self.device != root_device
            or self.uid != execution_uid
            or self.mode & 0o077
            or not (self.directory or self.regular)
            or (self.regular and self.links != 1)
        ):
            raise ValueError("Unsafe project entry")


@dataclass(frozen=True, slots=True)
class PrivateReadWindow:
    offset: int = 0
    length: int = 262_144

    def __post_init__(self) -> None:
        if (
            type(self.offset) is not int
            or type(self.length) is not int
            or not 0 <= self.offset < 2**63
            or not 1 <= self.length <= 262_144
        ):
            raise ValueError("Invalid read budget")


class PrivatePathAction(StrEnum):
    LIST = "file_list"
    INFO = "file_info"
    HASH = "file_hash"


@dataclass(frozen=True, slots=True)
class PrivateFileSelection:
    path: str

    def __post_init__(self) -> None:
        project_components(self.path)


@dataclass(frozen=True, slots=True)
class PrivatePathQuery(PrivateFileSelection):
    action: PrivatePathAction

    @property
    def tool(self) -> str:
        return self.action.value


@dataclass(frozen=True, slots=True)
class PrivateReadQuery(PrivateFileSelection):
    window: PrivateReadWindow = PrivateReadWindow()

    @property
    def tool(self) -> Literal["file_read"]:
        return "file_read"


type PrivateFileQuery = PrivatePathQuery | PrivateReadQuery
