from __future__ import annotations

from typing import Annotated

from briareus_mcp_resources import MCP_SURFACE_PATHS, resource_url, surface_base_url
from briareus_oidc import OidcTokenVerifier
from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl, TypeAdapter, UrlConstraints

from .auth_client import OidcMcpTokenVerifier
from .gateway_settings import GatewayAuthSettings

_ISSUER_URL: TypeAdapter[AnyHttpUrl] = TypeAdapter(
    Annotated[AnyHttpUrl, UrlConstraints(preserve_empty_path=True)]
)


def build_surface_auth(settings: GatewayAuthSettings) -> dict[str, RemoteAuthProvider]:
    settings.validate_bootstrap()
    if not settings.enabled:
        return {}
    authorization_server = _ISSUER_URL.validate_python(settings.issuer_url)
    result: dict[str, RemoteAuthProvider] = {}
    project_verifier = OidcTokenVerifier(settings)
    for surface in MCP_SURFACE_PATHS:
        verifier = OidcMcpTokenVerifier(
            project_verifier,
            resource_url(settings.public_base_url, surface),
        )
        result[surface] = RemoteAuthProvider(
            token_verifier=verifier,
            authorization_servers=[authorization_server],
            base_url=surface_base_url(settings.public_base_url, surface),
            scopes_supported=list(settings.authorization_scopes),
            challenge_scopes=list(settings.authorization_scopes),
            resource_name=f"Briareus {surface.title()}",
        )
    return result
