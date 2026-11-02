"""Replay identity and immutable claim state; storage and ciphers are external."""

from dataclasses import dataclass


class InvalidReplayInput(Exception):
    """The supplied idempotency key or persisted receipt is malformed."""


class ReplayFingerprintConflict(Exception):
    """A key was reused with a different canonical command payload."""


class ReplayPending(Exception):
    """The current durable claim has not completed."""


@dataclass(frozen=True, slots=True)
class ReplayIdentity:
    actor_scope: str
    project_scope: str
    operation: str
    key: str

    def require_valid(self) -> None:
        if not 1 <= len(self.key) <= 128 or not self.key.isascii() or not self.key.isprintable():
            raise InvalidReplayInput("Idempotency-Key must be 1-128 printable ASCII characters")


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    fingerprint: str
    status: str
    response_status: int | None
    response_ciphertext: str | None

    def require_completed(self, fingerprint: str) -> None:
        if self.fingerprint != fingerprint:
            raise ReplayFingerprintConflict("idempotency key reused with different request")
        if self.status != "completed" or self.response_ciphertext is None:
            raise ReplayPending("idempotent command has not completed")
