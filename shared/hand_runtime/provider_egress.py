"""HTTPS CONNECT implementation for the admitted public-only provider tunnel."""

import http.client
import os
import ssl

from .domain.provider_egress import ProviderTunnel
from .runtime_policy import runtime_policy


class ProviderConnection(http.client.HTTPSConnection):
    def __init__(
        self, tunnel: ProviderTunnel, context: ssl.SSLContext, effect_timeout: float | None
    ) -> None:
        super().__init__(tunnel.proxy_host, tunnel.proxy_port, timeout=10, context=context)
        self._effect_timeout = effect_timeout
        self.set_tunnel(tunnel.target_host, 443)

    def connect(self) -> None:
        # Connection establishment and provider execution have distinct bounds.
        self.timeout = 10
        super().connect()
        if self.sock is None:
            raise ConnectionError("Provider TLS connection unavailable")
        self.sock.settimeout(self._effect_timeout)
        self.timeout = self._effect_timeout


def provider_connection(
    base_url: str,
    *,
    verify_tls: bool = True,
    ca_cert_pem: str | None = None,
    timeout: float = 30,
) -> ProviderConnection:
    """Retain the client factory signature; current owner policy owns the deadline."""
    del timeout  # Provider client defaults cannot replace the current owner deadline.
    tunnel = ProviderTunnel.admit(
        base_url, os.environ.get("HTTPS_PROXY", ""), verify_tls=verify_tls
    )
    context = ssl.create_default_context(
        cadata=ca_cert_pem.replace("\\n", "\n") if ca_cert_pem else None
    )
    return ProviderConnection(tunnel, context, runtime_policy().execution_timeout_seconds)
