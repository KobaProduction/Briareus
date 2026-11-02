"""Current subject and exact Project authority under a separate peer lease."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from projects.domain.context import (
    ContextSelector,
    VerifiedAccessProjectPeer,
    VerifiedPanelContextPeer,
    access_peer_matches,
    current_expiry,
    exact_project_matches,
    membership_matches,
    panel_peer_matches,
)
from projects.domain.membership import CurrentRauthyPlatformMembership


class ContextError(Exception):
    def __init__(self, status: int, code: str, *, owner_reply: bool = False) -> None:
        super().__init__(code)
        self.status, self.code, self.owner_reply = status, code, owner_reply


class CurrentMembership(Protocol):
    async def resolve(
        self, *, issuer: str, subject: str
    ) -> CurrentRauthyPlatformMembership | None: ...
    async def resolve_project(
        self,
        *,
        issuer: str,
        subject: str,
        project_uuid: UUID,
    ) -> CurrentRauthyPlatformMembership | None: ...


@dataclass(frozen=True, slots=True)
class ProjectMembershipResponse:
    issuer: str
    subject: str
    actor_uuid: str
    project_uuid: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ActorContextResponse(ProjectMembershipResponse):
    permissions: tuple[Literal["use_resources", "approve_agent_session"], ...]
    role: Literal["user", "operator"]


@dataclass(frozen=True, slots=True)
class ResourceActorContextResponse(ActorContextResponse):
    project_owner_kind: Literal["user", "team"]
    project_owner_uuid: str


class ReadPanelContext:
    def __init__(self, source: CurrentMembership, now: Callable[[], datetime]) -> None:
        self._source, self._now = source, now

    async def execute(
        self,
        selector: ContextSelector,
        peer: VerifiedPanelContextPeer,
    ) -> CurrentRauthyPlatformMembership:
        if not panel_peer_matches(peer, selector, self._now()):
            raise ContextError(403, "PLATFORM_SERVICE_SCOPE_DENIED")
        try:
            if selector.project_uuid is None:
                result = await self._source.resolve(
                    issuer=selector.issuer, subject=selector.subject
                )
            else:
                result = await self._source.resolve_project(
                    issuer=selector.issuer,
                    subject=selector.subject,
                    project_uuid=selector.project_uuid,
                )
        except Exception:
            raise ContextError(503, "PLATFORM_SOURCE_UNAVAILABLE") from None
        if result is None:
            raise ContextError(403, "PLATFORM_MEMBERSHIP_REQUIRED")
        now = self._now()
        if peer.expires_at <= now:
            raise ContextError(503, "PLATFORM_TRUST_UNAVAILABLE")
        if not membership_matches(result, selector, now) or not exact_project_matches(
            result, selector.project_uuid
        ):
            raise ContextError(503, "PLATFORM_SOURCE_INVALID_RESPONSE")
        return replace(result, expires_at=min(result.expires_at, peer.expires_at))


class ReadAccessProjectContext:
    def __init__(self, source: CurrentMembership, now: Callable[[], datetime]) -> None:
        self._source, self._now = source, now

    async def execute(
        self,
        selector: ContextSelector,
        peer: VerifiedAccessProjectPeer,
        *,
        actor_context: bool,
    ) -> ProjectMembershipResponse:
        if not access_peer_matches(peer, selector, self._now()) or selector.project_uuid is None:
            raise ContextError(403, "PLATFORM_PROJECT_PROOF_DENIED")
        try:
            current = await self._source.resolve_project(
                issuer=selector.issuer,
                subject=selector.subject,
                project_uuid=selector.project_uuid,
            )
        except Exception:
            raise ContextError(
                503, "PLATFORM_PROJECT_SOURCE_UNAVAILABLE", owner_reply=True
            ) from None
        return self._result(selector, peer, current, actor_context)

    def _result(
        self,
        selector: ContextSelector,
        peer: VerifiedAccessProjectPeer,
        current: CurrentRauthyPlatformMembership | None,
        actor_context: bool,
    ) -> ProjectMembershipResponse:
        if current is None:
            raise ContextError(403, "PLATFORM_PROJECT_NOT_MEMBER", owner_reply=True)
        now = self._now()
        if peer.expires_at <= now:
            raise ContextError(503, "PLATFORM_PROJECT_PEER_UNAVAILABLE", owner_reply=True)
        if not membership_matches(current, selector, now) or not current_expiry(
            current.expires_at, now
        ):
            raise ContextError(503, "PLATFORM_PROJECT_PROOF_INVALID", owner_reply=True)
        visible = tuple(
            project
            for project in current.projects
            if (
                project.project_id == selector.project_uuid
                and "use_resources" in project.permissions
            )
        )
        if len(visible) != 1:
            raise ContextError(403, "PLATFORM_PROJECT_NOT_MEMBER", owner_reply=True)
        base = ProjectMembershipResponse(
            selector.issuer,
            selector.subject,
            str(current.user_id),
            str(selector.project_uuid),
            min(current.expires_at, peer.expires_at),
        )
        if not actor_context:
            return base
        project = visible[0]
        if peer.consumer == "resources":
            return ResourceActorContextResponse(
                base.issuer,
                base.subject,
                base.actor_uuid,
                base.project_uuid,
                base.expires_at,
                project.permissions,
                current.role,
                project.owner_kind,
                str(project.owner_id),
            )
        return ActorContextResponse(
            base.issuer,
            base.subject,
            base.actor_uuid,
            base.project_uuid,
            base.expires_at,
            project.permissions,
            current.role,
        )
