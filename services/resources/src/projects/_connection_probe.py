"""Compatibility entry point for the bounded provider verification adapter."""

from projects.domain.provider_connections import ProviderCheck, ProviderProbe
from projects.infrastructure.provider_verification import (
    PublicHTTPSConnection as PublicHTTPSConnection,
)
from projects.infrastructure.provider_verification import (
    verify_provider,
)


def check_connection(
    provider: str,
    base_url: str,
    token: str,
    auth_type: str,
    external_id: str = "",
    ca_cert_pem: str = "",
) -> ProviderCheck:
    return verify_provider(
        ProviderProbe(provider, base_url, token, auth_type, external_id, ca_cert_pem)
    )
