"""The authenticated BFF requests current human Web evidence from Authorization."""

from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from control_panel_api.domain.oidc_identity import PrivateOidcResourceCredential


@runtime_checkable
class HumanEffectPermits(Protocol):
    async def issue(
        self,
        *,
        project_uuid: UUID,
        request_uuid: UUID,
        body: bytes,
        credential: PrivateOidcResourceCredential,
        module: Literal["web", "files", "terminal", "reverse"] = "web",
    ) -> str: ...
