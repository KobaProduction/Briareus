"""Fixed attested Catalog HTTP channel and strict metadata-only response codec."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from control_panel_api.application.private_catalog_client import PrivateCatalogChannel
from control_panel_api.domain.catalog_metadata import (
    CatalogReadDenied,
    CatalogReadUnavailable,
    VerifiedCatalogSummary,
)
from control_panel_api.domain.private_catalog_client import (
    PrivateCatalogAuthority,
    PrivateCatalogQuery,
)

_DESTINATION = "http://briareus-resources:8000/internal/v1/resources/catalog/list"


@dataclass(frozen=True, slots=True)
class VerifiedCatalogTransport:
    client: httpx.AsyncClient
    transport: Literal["mtls", "unix-peer"]
    audience: Literal["briareus:resources"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedCatalogDelegation:
    issuer: Literal["rauthy"]
    actor_uuid: UUID
    project_uuid: UUID
    kind: Literal["integration", "variable"]
    bearer: SecretStr
    audience: Literal["briareus:resources"]
    expires_at: datetime


class TrustedCatalogPeerPort(Protocol):
    async def current_transport(self) -> VerifiedCatalogTransport: ...
    async def signed_catalog_delegation(
        self,
        *,
        actor_uuid: UUID,
        project_uuid: UUID,
        kind: Literal["integration", "variable"],
    ) -> VerifiedCatalogDelegation: ...


def _checked_transport(raw: object) -> VerifiedCatalogTransport:
    if not isinstance(raw, VerifiedCatalogTransport):
        raise CatalogReadUnavailable("Catalog actor/peer attestation not current")
    expiry: object = raw.expires_at
    if not isinstance(expiry, datetime):
        raise CatalogReadUnavailable("Catalog actor/peer attestation not current")
    return raw


def _checked_delegation(raw: object) -> VerifiedCatalogDelegation:
    if not isinstance(raw, VerifiedCatalogDelegation):
        raise CatalogReadUnavailable("Catalog actor/peer attestation not current")
    expiry: object = raw.expires_at
    if not isinstance(expiry, datetime):
        raise CatalogReadUnavailable("Catalog actor/peer attestation not current")
    return raw


class _Owner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["project", "team"]
    id: UUID


class _CatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_uuid: UUID
    kind: Literal["integration", "variable"]
    owner: _Owner
    key: str = Field(min_length=1, max_length=128)
    version: int = Field(strict=True, ge=1)


class _CatalogList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[_CatalogItem, ...] = Field(max_length=50)

    def summaries(self) -> tuple[VerifiedCatalogSummary, ...]:
        return tuple(
            VerifiedCatalogSummary(
                resource_uuid=item.resource_uuid,
                kind=item.kind,
                owner_kind=item.owner.kind,
                owner_uuid=item.owner.id,
                key=item.key,
                version=item.version,
            )
            for item in self.items
        )


class HttpPrivateCatalog:
    def __init__(
        self,
        connection: VerifiedCatalogTransport,
        delegation: VerifiedCatalogDelegation,
        query: PrivateCatalogQuery,
        now: Callable[[], datetime],
    ) -> None:
        self._connection, self._query, self._now = connection, query, now
        self.authority = PrivateCatalogAuthority(
            connection.transport,
            connection.audience,
            connection.expires_at,
            delegation.issuer,
            delegation.actor_uuid,
            delegation.project_uuid,
            delegation.kind,
            delegation.audience,
            delegation.expires_at,
            delegation.bearer,
        )

    async def read(self) -> tuple[VerifiedCatalogSummary, ...]:
        query = self._query
        try:
            async with self._connection.client.stream(
                "POST",
                _DESTINATION,
                follow_redirects=False,
                json={"project_uuid": str(query.project), "kind": query.kind, "limit": query.limit},
                headers={
                    "Authorization": "Bearer " + self.authority.bearer.get_secret_value(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            ) as response:
                raw = await _read_response(response)
        except (httpx.HTTPError, TimeoutError):
            raise CatalogReadUnavailable("Catalog transport unavailable") from None
        self.authority.require_after_read(self._now())
        try:
            return _CatalogList.model_validate_json(raw).summaries()
        except ValueError:
            raise CatalogReadUnavailable("untrusted private Catalog result") from None


async def _read_response(response: httpx.Response) -> bytes:
    if response.status_code in {401, 403}:
        raise CatalogReadDenied("private Catalog Project denied")
    if response.status_code != 200:
        raise CatalogReadUnavailable("Catalog source currently unavailable")
    if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise CatalogReadUnavailable("unexpected Catalog response MIME")
    raw = bytearray()
    async for chunk in response.aiter_bytes():
        if len(raw) + len(chunk) > 32768:
            raise CatalogReadUnavailable("Catalog response over maximum")
        raw.extend(chunk)
    return bytes(raw)


class AttestedPrivateCatalogPeer:
    def __init__(self, peer: TrustedCatalogPeerPort, now: Callable[[], datetime]) -> None:
        self._peer, self._now = peer, now

    async def open(self, query: PrivateCatalogQuery) -> PrivateCatalogChannel:
        connection = await self._peer.current_transport()
        delegation = await self._peer.signed_catalog_delegation(
            actor_uuid=query.actor, project_uuid=query.project, kind=query.kind
        )
        return HttpPrivateCatalog(
            _checked_transport(connection), _checked_delegation(delegation), query, self._now
        )
