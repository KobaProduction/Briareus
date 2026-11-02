"""Stable, owned project bytes are required before any Analysis upload."""

from dataclasses import dataclass

MAX_TRANSFER_BYTES = 256 * 1024**2


@dataclass(frozen=True)
class ProjectSourcePath:
    relative: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.relative, str)
            or not self.relative
            or "\\" in self.relative
            or "\0" in self.relative
        ):
            raise ValueError("Relative project file required")
        if any(part in {"", ".", ".."} for part in self.parts):
            raise ValueError("Relative project file required")

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.relative.split("/"))


@dataclass(frozen=True)
class SourceFingerprint:
    size_bytes: int
    modified_at_ns: int
    changed_at_ns: int

    def require_unchanged(self, after: "SourceFingerprint") -> None:
        if self != after:
            raise ValueError("Project file changed during transfer")


@dataclass(frozen=True)
class SourceDescriptor:
    uid: int
    gid: int
    mode: int
    device: int
    regular: bool
    links: int
    fingerprint: SourceFingerprint

    def require_owner(self, root_device: int) -> None:
        if self.uid != 1000 or self.gid != 1000 or self.mode & 0o022 or self.device != root_device:
            raise ValueError("Unsafe project file owner")

    def require_artifact(self) -> None:
        if not self.regular or self.links != 1 or self.fingerprint.size_bytes > MAX_TRANSFER_BYTES:
            raise ValueError("Bounded regular project file required")


def require_copied_size(size: int) -> None:
    if size > MAX_TRANSFER_BYTES:
        raise ValueError("Project file exceeds transfer limit")
