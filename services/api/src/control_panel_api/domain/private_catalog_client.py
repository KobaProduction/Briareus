"""Exact Catalog selectors and independently delegated metadata authority."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from control_panel_api.domain.approval_policy import uuid4 as _uuid_v4
from control_panel_api.domain.catalog_metadata import (
    CatalogReadDenied,
    CatalogReadUnavailable,
    VerifiedCatalogSummary,
)
from control_panel_api.domain.native_login import SecretText


@dataclass(frozen=True, slots=True)
class PrivateCatalogQuery:
    actor: UUID
    project: UUID
    kind: Literal["integration", "variable"]
    limit: int

    def require_valid(self) -> None:
        valid_owner = _uuid_v4(self.actor) and _uuid_v4(self.project)
        if (
            not valid_owner
            or self.kind not in {"integration", "variable"}
            or type(self.limit) is not int
            or not 1 <= self.limit <= 50
        ):
            raise CatalogReadDenied("invalid Project Catalog read selector")


@dataclass(frozen=True, slots=True)
class PrivateCatalogAuthority:
    transport: str
    transport_audience: str
    transport_expires_at: datetime
    issuer: str
    actor: UUID
    project: UUID
    kind: str
    audience: str
    expires_at: datetime
    bearer: SecretText = field(repr=False)

    def require_current(self, query: PrivateCatalogQuery, now: datetime) -> None:
        transport_current = (
            self.transport in {"mtls", "unix-peer"}
            and self.transport_audience == "briareus:resources"
            and self.transport_expires_at.tzinfo is not None
            and now < self.transport_expires_at <= now + timedelta(seconds=30)
        )
        expected = ("rauthy", query.actor, query.project, query.kind, "briareus:resources")
        actual = (self.issuer, self.actor, self.project, self.kind, self.audience)
        if not transport_current or actual != expected or self.expires_at.tzinfo is None:
            raise CatalogReadUnavailable("Catalog actor/peer attestation not current")
        if not now < self.expires_at <= self.transport_expires_at:
            raise CatalogReadUnavailable("Catalog actor/peer attestation not current")
        credential = self.bearer.get_secret_value()
        if (
            not 40 <= len(credential) <= 8192
            or not credential.isascii()
            or any(character.isspace() for character in credential)
        ):
            raise CatalogReadUnavailable("private Catalog bearer malformed")

    def require_after_read(self, now: datetime) -> None:
        if self.expires_at <= now:
            raise CatalogReadUnavailable("Catalog signed actor expired during read")


def require_catalog_page(
    query: PrivateCatalogQuery, items: tuple[VerifiedCatalogSummary, ...]
) -> None:
    seen: set[UUID] = set()
    for item in items:
        if (
            item.kind != query.kind
            or item.resource_uuid.version != 4
            or item.resource_uuid in seen
            or item.owner_uuid.version != 4
        ):
            raise CatalogReadUnavailable("Catalog item kind/owner invalid")
        seen.add(item.resource_uuid)
