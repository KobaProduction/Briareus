"""Chunk append invariants and immutable file observations."""

from dataclasses import dataclass

MAX_FILE_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    signature: tuple[int, int, int, int, int]
    size_bytes: int
    regular: bool


def require_chunk_size(
    offset: int, data_bytes: int, *, truncate: bool, max_file_bytes: int
) -> None:
    if type(offset) is not int or offset < 0 or (truncate and offset != 0):
        raise ValueError("Invalid chunk offset")
    if offset + data_bytes > min(max_file_bytes, MAX_FILE_BYTES):
        raise ValueError("File exceeds configured size limit")


def require_chunk_target(offset: int, *, truncate: bool, before: FileSnapshot | None) -> None:
    if before is not None and not before.regular:
        raise ValueError("Regular file required")
    if not truncate and offset != (before.size_bytes if before is not None else 0):
        raise ValueError("Chunk offset does not match current file size")
