"""Web account revision and draft credential invariants, independent of HTTP."""

from datetime import UTC, datetime


class AccountInputRejected(Exception):
    """Account fields or an attempted provider change are invalid."""


class AccountMissing(Exception):
    """The selected persisted account is unavailable."""


class StaleAccountRevision(Exception):
    """The submitted timestamp does not identify the current account revision."""


class AccountUpdateConflict(Exception):
    def __init__(self, current_updated_at: str | None) -> None:
        super().__init__("account changed since it was loaded; reload before saving")
        self.current_updated_at = current_updated_at


class CandidateVerificationTimedOut(Exception):
    """The verifier exceeded its bounded execution time."""


class CandidateVerificationFailed(Exception):
    """The candidate verifier failed or did not affirm the connection."""


def utc_timestamp(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def require_same_provider(selected: str, requested: str) -> None:
    if selected != requested:
        raise AccountInputRejected("provider cannot be changed")


def require_account_revision(expected: datetime | None, persisted: datetime) -> None:
    if expected is not None and utc_timestamp(expected) != utc_timestamp(persisted):
        raise StaleAccountRevision("account changed since it was loaded")


def require_candidate_credential(credential: str, *, existing: bool) -> None:
    if not credential.strip() and not existing:
        raise AccountInputRejected("credential is required for a new account")
