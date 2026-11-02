"""Exact expected body identity and configured upload limits."""

from dataclasses import dataclass


class AttachmentRejected(ValueError):
    """Attachment did not satisfy the requested transfer contract."""


def normalize_sha256(value: str) -> str:
    digest = value.strip().casefold()
    if digest and (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
        raise AttachmentRejected("expected_sha256 must be a 64-character hex digest")
    return digest


@dataclass(frozen=True, slots=True)
class AttachmentExpectation:
    max_bytes: int
    expected_size: int | None
    expected_sha256: str

    def __post_init__(self) -> None:
        if self.expected_size is not None and not 0 <= self.expected_size <= self.max_bytes:
            raise AttachmentRejected(f"expected_size must be between 0 and {self.max_bytes}")
        if self.max_bytes <= 0:
            raise AttachmentRejected("maximum attachment size must be positive")

    def require_declared(self, size: int | None) -> None:
        if size is None:
            return
        if not 0 <= size <= self.max_bytes:
            raise AttachmentRejected("attachment exceeds configured upload size limit")
        if self.expected_size is not None and size != self.expected_size:
            raise AttachmentRejected("attachment Content-Length does not match expected_size")

    def require_progress(self, total: int) -> None:
        if total > self.max_bytes:
            raise AttachmentRejected("attachment exceeds configured upload size limit")

    def require_complete(self, declared: int | None, total: int, sha256: str) -> None:
        if declared is not None and total != declared:
            raise AttachmentRejected("attachment body is shorter than Content-Length")
        if self.expected_size is not None and total != self.expected_size:
            raise AttachmentRejected(
                f"attachment size mismatch: expected {self.expected_size}, received {total}"
            )
        if self.expected_sha256 and sha256 != self.expected_sha256:
            raise AttachmentRejected(
                f"attachment SHA-256 mismatch: expected {self.expected_sha256}, found {sha256}"
            )
