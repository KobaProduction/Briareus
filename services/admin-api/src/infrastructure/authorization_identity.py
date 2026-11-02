from __future__ import annotations

from urllib.parse import quote

from application.web_session_contracts import LoginRequest
from application.web_session_contracts import WebUserView as LocalUserIdentity

from ._adapter_resources import _AuthorizationClient


class AuthorizationIdentityClient(_AuthorizationClient):
    async def authenticate(self, username: str, password: str) -> LocalUserIdentity | None:
        response = await self._client.post(
            "/internal/v1/authenticate",
            json=LoginRequest(username=username, password=password).model_dump(mode="json"),
        )
        if response.status_code == 401:
            return None
        response.raise_for_status()
        return LocalUserIdentity.model_validate_json(response.content)

    async def by_username(self, username: str) -> LocalUserIdentity:
        response = await self._client.get(
            f"/internal/v1/users/by-username/{quote(username, safe='')}"
        )
        response.raise_for_status()
        return LocalUserIdentity.model_validate_json(response.content)
