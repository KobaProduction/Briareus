"""The selectors require a current capability, not a concrete authority client."""

from typing import Protocol

from project_runtime_client.domain.authorization import (
    ProjectAction,
    ProjectInvocation,
    ProjectPermit,
)


class ResourceAuthorityPort(Protocol):
    async def require(
        self,
        invocation: ProjectInvocation,
        action: ProjectAction,
    ) -> ProjectPermit: ...
