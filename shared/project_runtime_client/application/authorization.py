"""Fetch a fresh service-authenticated permit and apply domain authority rules."""

import asyncio
import math
from datetime import UTC, datetime
from typing import Protocol

from project_runtime_client.domain.authorization import (
    ProjectAccessDenied,
    ProjectAction,
    ProjectInvocation,
    ProjectPermit,
)


class ProjectAccessPort(Protocol):
    async def authorize(
        self, invocation: ProjectInvocation, action: ProjectAction
    ) -> ProjectPermit: ...


class ProjectRuntimeAuthority:
    """Validates the backend decision before any private Project resource use.

    C1-B/C2 must bind a real port. No permissive in-process fallback exists.
    The permit is not a durable grant and must be refreshed before each action.
    """

    def __init__(
        self,
        port: ProjectAccessPort | None = None,
        *,
        operation_timeout_seconds: float = 10.0,
    ) -> None:
        if not math.isfinite(operation_timeout_seconds) or not 0 < operation_timeout_seconds <= 300:
            raise ValueError("Project authorization timeout must be finite and positive")
        self._operation_timeout_seconds = operation_timeout_seconds
        self._port = port

    async def require(self, invocation: ProjectInvocation, action: ProjectAction) -> ProjectPermit:
        if self._port is None:
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                permit = await self._port.authorize(invocation, action)
        except ProjectAccessDenied:
            raise
        except Exception as exc:
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_UNAVAILABLE") from exc
        if not isinstance(permit, ProjectPermit):
            raise ProjectAccessDenied("PROJECT_AUTHORIZATION_INVALID")
        permit.require_for(invocation, action, now=datetime.now(UTC))
        return permit
