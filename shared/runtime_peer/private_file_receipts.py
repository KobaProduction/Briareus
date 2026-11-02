"""Private Files facts shared without storage, framework or process dependencies."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PrivateFileEntry:
    path: str
    name: str
    type: Literal["file", "directory"]
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PrivateFileList[Entry]:
    path: str
    entries: tuple[Entry, ...]


@dataclass(frozen=True, slots=True)
class PrivateFileRead:
    path: str
    data_base64: str
    offset: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PrivateFileHash:
    path: str
    sha256: str
