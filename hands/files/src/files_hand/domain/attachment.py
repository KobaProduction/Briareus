"""Expected attachment identity and bounded transfer invariants."""

from dataclasses import dataclass

from .chunk_write import MAX_FILE_BYTES


@dataclass(frozen=True)
class AttachmentExpectation:
    size: int | None
    sha256: str

    def __post_init__(self) -> None:
        if self.size is not None and (
            type(self.size) is not int or not 0 <= self.size <= MAX_FILE_BYTES
        ):
            raise ValueError("Invalid expected attachment size")
        if self.sha256 and (
            len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ValueError("Invalid expected SHA-256")

    def require_declared(self, declared: int | None) -> None:
        if declared is not None and (
            not 0 <= declared <= MAX_FILE_BYTES or (self.size is not None and declared != self.size)
        ):
            raise ValueError("Attachment length exceeds expected bounds")

    def require_progress(self, total: int) -> None:
        if total > MAX_FILE_BYTES:
            raise ValueError("Attachment size limit exceeded")

    def require_complete(self, declared: int | None, total: int, sha256: str) -> None:
        if (
            (declared is not None and total != declared)
            or (self.size is not None and total != self.size)
            or (self.sha256 and sha256 != self.sha256)
        ):
            raise ValueError("Attachment size or digest mismatch")
