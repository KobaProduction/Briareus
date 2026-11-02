"""Analysis projection of a verified owner-local file entry."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class WorkspaceFileMetadata:
    path: str
    name: str
    size_bytes: int
    modified_at_ns: int
    mime_type: str
    type: Literal["file"] = "file"
