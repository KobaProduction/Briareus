"""Bounded stable-file reads exposed by the Node workspace."""

from dataclasses import dataclass

from .chunk_write import MAX_FILE_BYTES, FileSnapshot


@dataclass(frozen=True)
class FileReadWindow:
    offset: int = 0
    length: int = 1024 * 1024

    def __post_init__(self) -> None:
        if (
            type(self.offset) is not int
            or self.offset < 0
            or type(self.length) is not int
            or not 1 <= self.length <= 16 * 1024 * 1024
        ):
            raise ValueError("Bounded file read required")

    @property
    def page_bytes(self) -> int:
        return min(self.length, 262_144)

    def require_readable(self, before: FileSnapshot) -> None:
        if (
            not before.regular
            or before.size_bytes > MAX_FILE_BYTES
            or self.offset > before.size_bytes
        ):
            raise ValueError("Bounded regular file required")


def require_stable_read(before: FileSnapshot, after: FileSnapshot) -> None:
    if before.signature != after.signature:
        raise ValueError("File changed during read")
