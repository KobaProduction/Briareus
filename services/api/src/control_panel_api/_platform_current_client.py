"""Compose independently attested Platform membership projection reads."""

from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from control_panel_api.application.platform_projection_client import ResolvePlatformProjection
from control_panel_api.domain.platform_authority import ResolvedPlatformUser
from control_panel_api.domain.platform_projection_client import PlatformProjectionQuery
from control_panel_api.infrastructure.platform_projection_client import (
    AttestedPlatformProjectionPeer,
)
from control_panel_api.infrastructure.platform_projection_client import (
    TrustedPlatformPeerPort as TrustedPlatformPeerPort,
)
from control_panel_api.infrastructure.platform_projection_client import (
    VerifiedPanelDelegation as VerifiedPanelDelegation,
)
from control_panel_api.infrastructure.platform_projection_client import (
    VerifiedPlatformServiceTransport as VerifiedPlatformServiceTransport,
)

_utc_now = partial(datetime.now, UTC)


class PrivatePlatformCurrentClient:
    def __init__(self, *, peer: TrustedPlatformPeerPort) -> None:
        if peer is None:
            raise ValueError("authenticated Platform peer required")
        self._resolver = ResolvePlatformProjection(AttestedPlatformProjectionPeer(peer), _utc_now)

    async def resolve(self, *, issuer: str, subject: str) -> ResolvedPlatformUser | None:
        return await self._resolver.execute(PlatformProjectionQuery(issuer, subject, None))

    async def resolve_project(
        self,
        *,
        issuer: str,
        subject: str,
        project_uuid: UUID,
    ) -> ResolvedPlatformUser | None:
        return await self._resolver.execute_exact(
            PlatformProjectionQuery(issuer, subject, project_uuid)
        )
