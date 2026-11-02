"""Private RFC 7662 client; never polls the upstream identity provider."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from .application.token_status import TokenStatusQuery


class IntrospectionResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    active: bool
    client_id: str = ""
    sub: str = ""
    scope: str = ""
    aud: str = ""
    iss: str = ""
    exp: int | None = None


class LocalTokenStatusClient:
    def __init__(self, url: str, credential: str) -> None:
        if not credential:
            raise ValueError("A private OAuth introspection credential is required")
        self.url = url
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {credential}"},
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def is_active(self, query: TokenStatusQuery) -> bool:
        try:
            response = await self._client.post(self.url, data={"token": query.token})
            if response.status_code != 200:
                return False
            status = IntrospectionResult.model_validate(response.json())
        except (httpx.RequestError, ValidationError, ValueError):
            return False
        return (
            status.active
            and status.aud == query.audience
            and status.client_id == query.client_id
            and status.sub == query.subject
            and status.iss == query.issuer
            and status.exp == query.expires_at
            and "openid" in status.scope.split()
        )
