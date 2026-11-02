"""Obtain an actor-scoped current owner snapshot and fence its expiry."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from authorization.domain.session_reads import (
    ApprovalReadEntry,
    SessionReadEntry,
    SessionReadUnavailable,
    VerifiedApprovalActor,
)


@dataclass(frozen=True, slots=True)
class SessionReadQuery:
    project_uuid: UUID
    limit: int
    session_uuid: UUID | None = None


class SessionReadAuthorityPort(Protocol):
    async def verify(self) -> VerifiedApprovalActor: ...


class SessionReadRepositoryPort(Protocol):
    async def approvals(
        self,
        query: SessionReadQuery,
        actor: VerifiedApprovalActor,
    ) -> tuple[ApprovalReadEntry, ...]: ...

    async def sessions(
        self,
        query: SessionReadQuery,
        actor: VerifiedApprovalActor,
    ) -> tuple[SessionReadEntry, ...]: ...


class ReadProjectSessions:
    def __init__(
        self, authority: SessionReadAuthorityPort, repository: SessionReadRepositoryPort
    ) -> None:
        self.authority = authority
        self.repository = repository

    async def _actor(self, query: SessionReadQuery) -> VerifiedApprovalActor:
        actor = await self.authority.verify()
        actor.require_current(query.project_uuid, datetime.now(UTC))
        return actor

    @staticmethod
    def _require_snapshot(actor: VerifiedApprovalActor, count: int, limit: int) -> None:
        if count > limit or actor.expires_at <= datetime.now(UTC):
            raise SessionReadUnavailable

    async def approvals(self, query: SessionReadQuery) -> tuple[ApprovalReadEntry, ...]:
        actor = await self._actor(query)
        entries = await self.repository.approvals(query, actor)
        self._require_snapshot(actor, len(entries), query.limit)
        now = datetime.now(UTC)
        result: list[ApprovalReadEntry] = []
        for entry in entries:
            entry.require_valid(actor)
            result.append(replace(entry, allowed_actions=entry.actions(actor, now)))
        self._require_snapshot(actor, len(result), query.limit)
        return tuple(result)

    async def sessions(self, query: SessionReadQuery) -> tuple[SessionReadEntry, ...]:
        actor = await self._actor(query)
        entries = await self.repository.sessions(query, actor)
        self._require_snapshot(actor, len(entries), query.limit)
        now = datetime.now(UTC)
        result: list[SessionReadEntry] = []
        for entry in entries:
            entry.require_valid(actor)
            status = entry.current_status(now)
            actions = ("revoke",) if actor.can_approve and status == "active" else ()
            result.append(replace(entry, status=status, allowed_actions=actions))
        self._require_snapshot(actor, len(result), query.limit)
        return tuple(result)
