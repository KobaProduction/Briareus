"""Source files, strict JSON shapes and bounded fixed-origin HTTPS adapters."""

from __future__ import annotations

import hashlib
import json
import ssl
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from .application import HttpObservation, ProbeRoute
from .domain import (
    PRIVATE_JWK_FIELDS,
    DiscoveryEvidence,
    ProviderEndpoints,
    PublicKeyEvidence,
    RouteStatus,
    SourceSnapshot,
)
from .messages import DatabaseInventoryMessage, DiscoveryMessage, PublicKeyMetadata

MAX_BYTES = 131_072
TIMEOUT = 8


@dataclass(frozen=True, slots=True)
class LocalProviderSource:
    directory: Path

    def read(self) -> SourceSnapshot:
        root = self.directory
        return SourceSnapshot(
            (root / "docker-compose.yaml").read_text(),
            (root / "docker-compose.coolify.yaml").read_text(),
            (root / "postgres-entrypoint.sh").read_text(),
            (root / "provider-db-health.sh").read_text(),
            (root / "Dockerfile").read_text(),
            tuple((root / "Dockerfile.dockerignore").read_text().splitlines()),
            (root / "owner-bootstrap.psql").read_text(),
            (root / "owner-readiness.psql").read_text(),
            DatabaseInventoryMessage.model_validate_json(
                (root / "config/owner-databases.json").read_text()
            ).inventory(),
        )


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        _request: Request,
        _fp: object,
        _code: int,
        _msg: str,
        _headers: object,
        _new_url: str,
    ) -> None:
        return None


@dataclass(frozen=True, slots=True)
class FixedOriginProbe:
    origin: str

    def request(self, path: str) -> HttpObservation:
        url = self.origin + path
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "briareus.koba-nexus.ru":
            raise ValueError("outside approved public provider")
        request = Request(  # noqa: S310 -- HTTPS and exact authority were validated immediately above
            url,
            headers={
                "Accept": "application/json, text/html",
                "User-Agent": "Briareus-ProviderContract/1",
            },
            method="GET",
        )
        # Neither redirects nor process proxy variables may redirect evidence requests.
        opener = build_opener(
            ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context())
        )
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                raw = response.read(MAX_BYTES + 1)
                status = response.status
        except HTTPError as error:
            with error:
                raw = error.read(MAX_BYTES + 1)
            status = error.code
        if len(raw) > MAX_BYTES:
            raise ValueError("provider response exceeds allowed size")
        return HttpObservation(status, raw)

    def routes(self, routes: tuple[ProbeRoute, ...]) -> tuple[RouteStatus, ...]:
        with ThreadPoolExecutor(max_workers=len(routes)) as pool:
            responses = pool.map(self.request, (route.path for route in routes))
            return tuple(
                RouteStatus(route.name, route.path, response.status)
                for route, response in zip(routes, responses, strict=True)
            )


class ProviderJsonCodec:
    def discovery(self, raw: bytes, expected: ProviderEndpoints) -> DiscoveryEvidence:
        return DiscoveryMessage.model_validate_json(raw).evidence(expected)

    def public_keys(self, observation: HttpObservation) -> PublicKeyEvidence:
        if observation.status != 200:
            return PublicKeyEvidence(observation.status)
        value: object = json.loads(observation.body)
        if not isinstance(value, dict):
            raise ValueError("provider JWKS must be a JSON object")
        keys = value.get("keys", [])
        if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
            raise ValueError("provider JWKS keys must be an array of objects")
        safe = bool(keys)
        for key in keys:
            metadata = PublicKeyMetadata.model_validate(key)
            safe = safe and not (PRIVATE_JWK_FIELDS & set(key)) and bool(metadata.kid)
        # Fingerprint the complete provider keyset, including fields outside the
        # projection. The raw document never becomes an application contract.
        digest = hashlib.sha256(json.dumps(keys, sort_keys=True, separators=(",", ":")).encode())
        return PublicKeyEvidence(200, len(keys), safe, digest.hexdigest())
