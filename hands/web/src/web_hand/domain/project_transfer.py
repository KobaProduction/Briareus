"""Shared project paths and entry ownership are transfer invariants."""

import stat
import unicodedata
from dataclasses import dataclass

from modules.workspace_compat.domain.transfers import WorkspaceFileError


@dataclass(frozen=True, slots=True)
class ProjectTransferPath:
    value: str

    def parts(self) -> tuple[str, ...]:
        self._require_canonical(self.value)
        parts = tuple(self.value.split("/"))
        if any(part in {"", ".", ".."} or part.startswith(".briareus-") for part in parts):
            raise WorkspaceFileError("Canonical relative workspace path required")
        return parts

    @staticmethod
    def _require_canonical(value: object) -> None:
        if (
            not isinstance(value, str)
            or not value
            or not unicodedata.is_normalized("NFC", value)
            or value.startswith("/")
            or "\\" in value
            or "\0" in value
        ):
            raise WorkspaceFileError("Canonical relative workspace path required")


@dataclass(frozen=True, slots=True)
class ProjectEntryFacts:
    mode: int
    uid: int
    gid: int
    links: int
    device: int

    def require_safe(self, *, directory: bool, device: int | None) -> None:
        kind_valid = stat.S_ISDIR(self.mode) if directory else stat.S_ISREG(self.mode)
        if (
            not kind_valid
            or self.uid != 1000
            or self.gid != 1000
            or self.mode & 0o022
            or (not directory and self.links != 1)
            or (device is not None and self.device != device)
        ):
            raise WorkspaceFileError("Unsafe shared workspace entry")
