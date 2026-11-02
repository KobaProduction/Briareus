"""Adapters for the existing Identity client and retained configured credential pair."""

import hmac

from domain.web_session import WebIdentityUnavailable, WebUser

from infrastructure.authorization_identity import AuthorizationIdentityClient
from service_runtime._reference_bindings import _ClientBinding


class LegacyWebIdentity(_ClientBinding[AuthorizationIdentityClient]):
    async def authenticate(self, username: str, password: str) -> WebUser | None:
        try:
            identity = await self._client.authenticate(username, password)
        except Exception as exc:
            raise WebIdentityUnavailable from exc
        return None if identity is None else identity.domain()

    async def by_username(self, username: str) -> WebUser:
        try:
            identity = await self._client.by_username(username)
        except Exception as exc:
            raise WebIdentityUnavailable from exc
        return identity.domain()


class LegacyWebCredentials:
    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password

    def authenticate(self, username: str, password: str) -> str | None:
        valid_user = hmac.compare_digest(username, self._username)
        valid_password = hmac.compare_digest(password, self._password)
        return self._username if valid_user and valid_password else None
