"""Private typed references for existing application constructor assignments."""

from collections.abc import Callable
from datetime import datetime


class _SessionsBinding[SessionsT]:
    def __init__(self, sessions: SessionsT) -> None:
        self._sessions = sessions


class _PeerClockBinding[PeerT]:
    def __init__(self, peer: PeerT, now: Callable[[], datetime]) -> None:
        self._peer = peer
        self._now = now


class _SignatureBinding[SignatureT]:
    def __init__(self, signature: SignatureT) -> None:
        self._signature = signature


class _ManagementBinding[AuthorityT, OwnerT, EventsT]:
    def __init__(self, authority: AuthorityT, owner: OwnerT | None, events: EventsT) -> None:
        self._authority, self._owner, self._events = authority, owner, events
