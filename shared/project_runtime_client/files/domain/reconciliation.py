"""An unknown reservation resolves only to its exact successor or proven absence."""

from dataclasses import dataclass


class ReconciliationRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReconciliationObservation:
    expected_version: int
    observed_version: int
    confirmed_absent: bool
    inode_digest: str | None
    size_bytes: int
    content_digest: str | None
    expected_size: int
    expected_digest: str

    def require(self) -> bool:
        if self.observed_version == self.expected_version + 1:
            if self.confirmed_absent or self.inode_digest is None:
                raise ReconciliationRejected("A6_FILES_RECONCILIATION_INODE_REQUIRED")
            if (self.content_digest, self.size_bytes) != (self.expected_digest, self.expected_size):
                raise ReconciliationRejected("A6_FILES_RECONCILIATION_CONTENT_MISMATCH")
            return False
        if self.observed_version == self.expected_version:
            if not self.confirmed_absent or self.inode_digest is not None or self.size_bytes != 0:
                raise ReconciliationRejected("A6_FILES_ABSENCE_NOT_PROVEN")
            return True
        raise ReconciliationRejected("A6_FILES_RECONCILIATION_VERSION_INVALID")
