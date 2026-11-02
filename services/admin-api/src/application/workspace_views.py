"""Typed workspace administration read models; JSON belongs to the adapters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileWorkspaceStatus:
    root: str
    free_bytes: int
    used_bytes: int
    total_bytes: int
    free_display: str
    used_display: str
    total_display: str


@dataclass(frozen=True, slots=True)
class FileWorkspaceStats(FileWorkspaceStatus):
    files: int
    size_bytes: int
    size_display: str
