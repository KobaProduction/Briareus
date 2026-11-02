"""Authorize one bounded metadata read against the current signed actor scope."""

from typing import Protocol

from control_panel_api.application._constructor_bindings import _PeerClockBinding
from control_panel_api.domain.catalog_metadata import CatalogReadUnavailable, VerifiedCatalogSummary
from control_panel_api.domain.private_catalog_client import (
    PrivateCatalogAuthority,
    PrivateCatalogQuery,
    require_catalog_page,
)


class PrivateCatalogChannel(Protocol):
    @property
    def authority(self) -> PrivateCatalogAuthority: ...
    async def read(self) -> tuple[VerifiedCatalogSummary, ...]: ...


class PrivateCatalogPeer(Protocol):
    async def open(self, query: PrivateCatalogQuery) -> PrivateCatalogChannel: ...


class ReadPrivateCatalog(_PeerClockBinding[PrivateCatalogPeer]):
    async def execute(self, query: PrivateCatalogQuery) -> tuple[VerifiedCatalogSummary, ...]:
        query.require_valid()
        channel = await self._open(query)
        channel.authority.require_current(query, self._now())
        items = await channel.read()
        require_catalog_page(query, items)
        return items

    async def _open(self, query: PrivateCatalogQuery) -> PrivateCatalogChannel:
        try:
            return await self._peer.open(query)
        except CatalogReadUnavailable:
            raise
        except Exception:
            raise CatalogReadUnavailable("trusted Catalog service peer unavailable") from None
