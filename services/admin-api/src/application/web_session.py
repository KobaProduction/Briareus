"""Select the existing configured authority and admit its verified administrator."""

from typing import Protocol

from domain.web_session import WebIdentityUnavailable, WebInvalidCredentials, WebUser


class WebIdentityPort(Protocol):
    async def authenticate(self, username: str, password: str) -> WebUser | None: ...
    async def by_username(self, username: str) -> WebUser: ...


class RetainedWebCredentials(Protocol):
    def authenticate(self, username: str, password: str) -> str | None: ...


class LoginWebAdministrator:
    def __init__(
        self,
        identity: WebIdentityPort | None,
        credentials: RetainedWebCredentials,
        *,
        remote_authority: bool,
    ) -> None:
        self._identity = identity
        self._credentials = credentials
        self._remote_authority = remote_authority

    async def execute(self, username: str, password: str) -> str:
        if not self._remote_authority:
            authenticated = self._credentials.authenticate(username, password)
            if authenticated is None:
                raise WebInvalidCredentials
            return authenticated
        if self._identity is None:
            raise WebIdentityUnavailable
        user = await self._identity.authenticate(username, password)
        if user is None:
            raise WebInvalidCredentials
        user.require_login()
        return user.username


class CurrentWebAdministrator:
    def __init__(self, identity: WebIdentityPort | None) -> None:
        self._identity = identity

    async def execute(self, username: str) -> WebUser:
        if self._identity is None:
            raise WebIdentityUnavailable
        user = await self._identity.by_username(username)
        user.require_current()
        return user
