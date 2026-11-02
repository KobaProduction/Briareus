"""Dedicated rootless supervisor placement and private ingress ownership."""

import stat
from dataclasses import dataclass


@dataclass(frozen=True)
class SupervisorSandbox:
    uid: int
    no_new_privileges: bool
    effective_capabilities: int
    read_only_root: bool
    parent_uid: int

    def require_isolated(self) -> None:
        if (
            self.uid != 0
            or not self.no_new_privileges
            or self.effective_capabilities != (1 << 5 | 1 << 6 | 1 << 7)
            or not self.read_only_root
            or self.parent_uid == 0
        ):
            raise ValueError("Dedicated rootless supervisor placement required")


@dataclass(frozen=True)
class SupervisorPath:
    mode: int
    uid: int

    def require_directory(self) -> None:
        if not stat.S_ISDIR(self.mode) or (self.uid, stat.S_IMODE(self.mode)) != (0, 0o700):
            raise ValueError("Private supervisor socket directory required")

    def require_replaceable_socket(self) -> None:
        if not stat.S_ISSOCK(self.mode) or self.uid != 0:
            raise ValueError("Foreign supervisor socket")
