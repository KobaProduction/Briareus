from __future__ import annotations

from typing import Annotated

from briareus_oidc import OidcTokenVerifier
from briareus_service_catalog import BUILTIN_SERVICES, ServiceDefinition
from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl, TypeAdapter, UrlConstraints

from .auth_client import OidcMcpTokenVerifier
from .gateway_settings import GatewayAuthSettings

_ISSUER_URL: TypeAdapter[AnyHttpUrl] = TypeAdapter(
    Annotated[AnyHttpUrl, UrlConstraints(preserve_empty_path=True)]
)


def build_service_auth(
    settings: GatewayAuthSettings,
    service: ServiceDefinition,
    verifier: OidcTokenVerifier | None = None,
) -> RemoteAuthProvider | None:
    settings.validate_bootstrap()
    if not settings.enabled:
        return None
    base = settings.public_base_url.rstrip("/") + service.mcp_path.removesuffix("/mcp")
    return RemoteAuthProvider(
        token_verifier=OidcMcpTokenVerifier(verifier or OidcTokenVerifier(settings), base + "/mcp"),
        authorization_servers=[_ISSUER_URL.validate_python(settings.issuer_url)],
        base_url=base,
        scopes_supported=list(settings.authorization_scopes),
        challenge_scopes=list(settings.authorization_scopes),
        resource_name=f"Briareus {service.name}",
    )


def build_surface_auth(settings: GatewayAuthSettings) -> dict[str, RemoteAuthProvider]:
    settings.validate_bootstrap()
    verifier = OidcTokenVerifier(settings) if settings.enabled else None
    result: dict[str, RemoteAuthProvider] = {}
    for service in BUILTIN_SERVICES:
        auth = build_service_auth(settings, service, verifier)
        if auth is not None:
            result[service.id] = auth
    return result
