"""Read-only source and fixed-origin provider evidence scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .domain import (
    DiscoveryEvidence,
    ProviderEndpoints,
    PublicKeyEvidence,
    PublicReport,
    RouteStatus,
    SourceReport,
    SourceSnapshot,
    inspect_source,
)


@dataclass(frozen=True, slots=True)
class HttpObservation:
    status: int
    body: bytes


@dataclass(frozen=True, slots=True)
class ProbeRoute:
    name: str
    path: str


class SourceReader(Protocol):
    def read(self) -> SourceSnapshot: ...


class PublicProbe(Protocol):
    def request(self, path: str) -> HttpObservation: ...

    def routes(self, routes: tuple[ProbeRoute, ...]) -> tuple[RouteStatus, ...]: ...


class PublicMetadataCodec(Protocol):
    def discovery(self, raw: bytes, expected: ProviderEndpoints) -> DiscoveryEvidence: ...

    def public_keys(self, observation: HttpObservation) -> PublicKeyEvidence: ...


@dataclass(frozen=True, slots=True)
class InspectSource:
    source: SourceReader

    def execute(self) -> SourceReport:
        return inspect_source(self.source.read())


@dataclass(frozen=True, slots=True)
class InspectPublicProvider:
    probe: PublicProbe
    codec: PublicMetadataCodec
    endpoints: ProviderEndpoints
    routes: tuple[ProbeRoute, ...]

    def execute(self) -> PublicReport:
        discovery = self.probe.request("/auth/v1/.well-known/openid-configuration")
        if discovery.status != 200:
            return PublicReport(discovery.status)
        evidence = self.codec.discovery(discovery.body, self.endpoints)
        keys = self.codec.public_keys(self.probe.request("/auth/v1/oidc/certs"))
        return PublicReport(200, evidence, keys, self.probe.routes(self.routes))
