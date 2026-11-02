"""Compose metadata-only reads over the independently attested Catalog channel."""

from datetime import UTC, datetime
from functools import partial
from typing import Literal
from uuid import UUID

from control_panel_api.application.private_catalog_client import ReadPrivateCatalog
from control_panel_api.domain.catalog_metadata import VerifiedCatalogSummary
from control_panel_api.domain.private_catalog_client import PrivateCatalogQuery
from control_panel_api.infrastructure.private_catalog_client import AttestedPrivateCatalogPeer
from control_panel_api.infrastructure.private_catalog_client import (
    TrustedCatalogPeerPort as TrustedCatalogPeerPort,
)
from control_panel_api.infrastructure.private_catalog_client import (
    VerifiedCatalogDelegation as VerifiedCatalogDelegation,
)
from control_panel_api.infrastructure.private_catalog_client import (
    VerifiedCatalogTransport as VerifiedCatalogTransport,
)

_utc_now = partial(datetime.now, UTC)


class PrivateCatalogMetadataClient:
    def __init__(self, *, trusted_peer: TrustedCatalogPeerPort) -> None:
        if trusted_peer is None:
            raise ValueError("Catalog read needs trusted private actor peer")
        self._reader = ReadPrivateCatalog(
            AttestedPrivateCatalogPeer(trusted_peer, _utc_now), _utc_now
        )

    async def list_metadata(
        self,
        *,
        actor: UUID,
        project: UUID,
        kind: Literal["integration", "variable"],
        limit: int,
    ) -> tuple[VerifiedCatalogSummary, ...]:
        return await self._reader.execute(PrivateCatalogQuery(actor, project, kind, limit))
