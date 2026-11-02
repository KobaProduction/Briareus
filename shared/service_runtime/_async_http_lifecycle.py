"""Existing unconditional and owned-only HTTPX close contracts."""

from httpx import AsyncClient


class _AsyncClientClose:
    _client: AsyncClient

    async def close(self) -> None:
        await self._client.aclose()


class _OwnedClient(_AsyncClientClose):
    _owns_client: bool

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
