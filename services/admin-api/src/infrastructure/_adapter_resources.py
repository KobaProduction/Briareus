"""Resource ownership shared by the Admin storage and Authorization adapters."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from service_runtime._async_http_lifecycle import _AsyncClientClose


class _SqlAlchemyRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions


class _AuthorizationClient(_AsyncClientClose):
    def __init__(self, *, base_url: str, service_token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=5.0,
            headers={"Authorization": f"Bearer {service_token}"},
        )
