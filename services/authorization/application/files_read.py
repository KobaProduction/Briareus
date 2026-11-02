"""Obtain fresh independent authority before releasing a Files read receipt."""

from datetime import datetime
from typing import Protocol

from authorization.domain.files_read import (
    ReadAuthorization,
    ReadCaller,
    ReadGrant,
    ReadResource,
    ReadScope,
    authorize_read,
)


class ReadAuthorities(Protocol):
    def current_resource(self) -> ReadResource: ...

    async def current_grant(self) -> ReadGrant: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class DecideFilesRead:
    def __init__(self, authorities: ReadAuthorities, clock: Clock) -> None:
        self._authorities = authorities
        self._clock = clock

    async def execute(self, scope: ReadScope, caller: ReadCaller) -> ReadAuthorization:
        caller.require_scope(scope, self._clock.now())
        initial = self._authorities.current_resource()
        initial.require_revision(scope)
        grant = await self._authorities.current_grant()
        grant.require_scope(scope, caller, self._clock.now())
        # SQL/Cedar may consume the first proof; a new revision cannot extend it.
        current = self._authorities.current_resource()
        current.require_revision(scope)
        return authorize_read(caller, grant, initial, current, self._clock.now())
