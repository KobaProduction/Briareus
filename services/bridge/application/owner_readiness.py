"""Read-only admission against four independently authoritative owner schemas."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol

from bridge.domain.project_dispatch import (
    OWNER_SERVICES,
    ExpectedOwnerSchema,
    OwnerServiceName,
    ProjectGatewayDispatchUnavailable,
    VerifiedOwnerReadiness,
    require_matching_owner_schema,
)
from modules.project_runtime import ProjectInvocation


class ProjectOwnerReadinessPort(Protocol):
    """Verify pinned signature, service peer, DB identity/role, head and freshness."""

    async def require_current_owner_schema(
        self,
        invocation: ProjectInvocation,
        *,
        owner: OwnerServiceName,
    ) -> VerifiedOwnerReadiness: ...


class ProjectOwnerReleaseManifestPort(Protocol):
    """Supply the separately trusted, version-locked release expectation."""

    async def expected_schema(self, owner: OwnerServiceName) -> ExpectedOwnerSchema: ...


class RequireOwnerReadiness:
    def __init__(
        self,
        readiness: ProjectOwnerReadinessPort,
        manifest: ProjectOwnerReleaseManifestPort,
    ) -> None:
        self._readiness = readiness
        self._manifest = manifest

    async def execute(self, invocation: ProjectInvocation, *, timeout_seconds: float) -> None:
        try:
            async with asyncio.timeout(min(timeout_seconds, 10.0)):
                for owner in OWNER_SERVICES:
                    expected = await self._manifest.expected_schema(owner)
                    snapshot = await self._readiness.require_current_owner_schema(
                        invocation, owner=owner
                    )
                    require_matching_owner_schema(owner, snapshot, expected, now=datetime.now(UTC))
        except Exception as exc:
            raise ProjectGatewayDispatchUnavailable("PROJECT_OWNER_SCHEMA_UNAVAILABLE") from exc
