"""Private typed references for identical authority constructor and deadline checks."""

from collections.abc import Callable
from datetime import datetime

from projects.domain.management import ManagementError


class _ReadAuthorityBinding[ReaderT, AuthorityT]:
    def __init__(self, reader: ReaderT, authority: AuthorityT, now: Callable[[], datetime]) -> None:
        self._reader = reader
        self._authority = authority
        self._now = now


class _FreshAuthority:
    _now: Callable[[], datetime]

    def _fresh(self, deadline: datetime, code: str = "PLATFORM_AUTHORITY_EXPIRED") -> None:
        if self._now() >= deadline:
            raise ManagementError(503, code)
