from typing import Literal

from briareus_json_values import StrictModel


class FileEntry(StrictModel):
    path: str
    name: str
    type: Literal["file", "directory"]
    size_bytes: int
    modified_at_ns: int
    mime_type: str = ""


class FileListing(StrictModel):
    path: str
    entries: list[FileEntry]
    count: int
    total: int
    offset: int
    limit: int
    truncated: bool


class FileStatus(StrictModel):
    root: str
    free_bytes: int
    used_bytes: int
    total_bytes: int
    free_display: str
    used_display: str
    total_display: str


class FileStats(FileStatus):
    files: int
    size_bytes: int
    size_display: str


class FileDeletion(StrictModel):
    path: str
    deleted: bool = False
    already_absent: bool = False
