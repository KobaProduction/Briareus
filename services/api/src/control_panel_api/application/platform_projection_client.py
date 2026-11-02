"""Resolve owner projections only within the independently delegated lifetime."""

from typing import Protocol

from control_panel_api.application._constructor_bindings import _PeerClockBinding
from control_panel_api.application.platform_membership import PlatformMembershipUnavailable
from control_panel_api.domain.platform_authority import ResolvedPlatformUser
from control_panel_api.domain.platform_projection_client import (
    PlatformProjectionAuthority,
    PlatformProjectionInvalid,
    PlatformProjectionQuery,
    require_current_projection,
)


class PlatformProjectionChannel(Protocol):
    @property
    def authority(self) -> PlatformProjectionAuthority: ...
    async def read(self) -> ResolvedPlatformUser | None: ...


class PlatformProjectionPeer(Protocol):
    async def open(self, query: PlatformProjectionQuery) -> PlatformProjectionChannel: ...


class ResolvePlatformProjection(_PeerClockBinding[PlatformProjectionPeer]):
    async def execute_exact(self, query: PlatformProjectionQuery) -> ResolvedPlatformUser | None:
        try:
            query.require_exact_project()
        except PlatformProjectionInvalid as exc:
            raise PlatformMembershipUnavailable(str(exc)) from None
        return await self.execute(query)

    async def execute(self, query: PlatformProjectionQuery) -> ResolvedPlatformUser | None:
        try:
            query.require_selector()
            channel = await self._open(query)
            channel.authority.require_current(query, self._now())
            current = await channel.read()
            if current is not None:
                require_current_projection(
                    query,
                    current,
                    authority_expires_at=channel.authority.expires_at,
                    now=self._now(),
                )
            return current
        except PlatformProjectionInvalid as exc:
            raise PlatformMembershipUnavailable(str(exc)) from None

    async def _open(self, query: PlatformProjectionQuery) -> PlatformProjectionChannel:
        try:
            return await self._peer.open(query)
        except PlatformProjectionInvalid:
            raise
        except Exception:
            raise PlatformProjectionInvalid("private Platform peer unavailable") from None
