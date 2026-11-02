"""Fencing and history policies for one Node's durable execution facts."""

from dataclasses import dataclass
from uuid import UUID


class JournalRejected(ValueError):
    """The caller has no current authority for this journal request."""


class JournalConflict(ValueError):
    """The request conflicts with immutable execution history or a writer fence."""


class JournalUnavailable(RuntimeError):
    """The owner cannot durably record an execution fact."""


@dataclass(frozen=True)
class WriterLease:
    session_uuid: UUID
    epoch: int
    expires_at: int
    cursor: int

    def require_writer(self, session: UUID, epoch: int | None, now: int) -> None:
        if self.session_uuid != session or self.epoch != epoch or self.expires_at <= now:
            raise JournalConflict("Current execution writer lease required")


def acquire_writer(
    previous: WriterLease | None, session: UUID, *, now: int, seconds: int
) -> WriterLease:
    if previous is None:
        return WriterLease(session, 1, now + seconds, 0)
    if previous.expires_at > now:
        if previous.session_uuid != session:
            raise JournalConflict("Only one controller may own this journal")
        return WriterLease(session, previous.epoch, now + seconds, previous.cursor)
    return WriterLease(session, previous.epoch + 1, now + seconds, previous.cursor)


def require_replay_window(cursor: int, first: int | None, last: int) -> None:
    if (first is not None and cursor < first - 1) or cursor > last:
        raise JournalConflict("Event replay window lost; obtain authoritative inventory")


def require_configuration(sequence: int, previous_sequence: int | None, identical: bool) -> bool:
    if previous_sequence is not None and (
        sequence < previous_sequence or (sequence == previous_sequence and not identical)
    ):
        raise JournalConflict("Stale or conflicting node configuration")
    return previous_sequence != sequence or not identical


def require_operation_replay(sequence: int, previous_sequence: int, identical: bool) -> None:
    if sequence != previous_sequence or not identical:
        raise JournalConflict("Operation identity reused with different command")
