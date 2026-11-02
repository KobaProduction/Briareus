"""SSRF-aware HTTPS attachment transport with deployment-owned proxy support.

Only a verified *public* destination IP may be contacted, including through a
configured HTTP CONNECT proxy. Proxy configuration comes from the PROCESS
environment, never an MCP tool argument. The proxy is dialed by a pinned
resolved address and CONNECT uses a validated numeric destination IP (not a
second hostname lookup). TLS SNI and certificate verification use the original
hostname. A proxy unable to support numeric CONNECT fails closed.

HTTPS proxies (TLS to proxy itself) are explicitly unsupported rather than
silently skipped, since wrapping both TLS hops needs a separately reviewed
transport. No request parameters can supply a proxy or override this policy.
"""

from __future__ import annotations

import base64 as base64
import http as http
import ipaddress as ipaddress
import socket as socket
import ssl as ssl
import urllib.parse
from collections.abc import Callable as Callable
from dataclasses import dataclass as dataclass
from types import TracebackType as TracebackType

from modules.workspace_compat.legacy_store import WorkspaceFileError as WorkspaceFileError
from project_runtime_client.files.infrastructure.public_attachment import (
    PinnedAttachmentResponse as PinnedAttachmentResponse,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    _EgressProxy as _EgressProxy,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    _PinnedTLSSetup as _SharedPinnedTLSSetup,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    _PublicEndpoint as _PublicEndpoint,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    _resolve_addresses as _resolve_addresses,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    _trusted_proxy_for_host as _shared_trusted_proxy,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    validate_public_attachment_url as validate_public_attachment_url,
)


def _trusted_proxy(endpoint: _PublicEndpoint) -> _EgressProxy | None:
    host = endpoint.uri.hostname
    if host is None:
        raise AssertionError
    return _shared_trusted_proxy(endpoint, host)


class _PinnedTLSConnection(_SharedPinnedTLSSetup):
    def __init__(self, endpoint: _PublicEndpoint, proxy: _EgressProxy | None) -> None:
        host = endpoint.uri.hostname
        if host is None:
            raise AssertionError
        super().__init__(host, port=endpoint.uri.port or 443, timeout=60)
        self._target_addresses = endpoint.addresses
        self._proxy = proxy

    def connect(self) -> None:
        """Dial only vetted addresses; HTTP CONNECT must also target an IP."""
        failure: OSError | None = None
        for target in self._target_addresses:
            attempts = self._proxy.pinned_ips if self._proxy else (target,)
            port = self._proxy.port if self._proxy else self.port
            for address in attempts:
                sock: socket.socket | None = None
                try:
                    sock = socket.create_connection((address, port), timeout=self.timeout)
                    self._establish_tls(target, sock)
                    return
                except OSError as exc:
                    failure = exc
                finally:
                    if self.sock is sock and sock is not None:
                        sock.close()
                        self.sock = None
        raise WorkspaceFileError("attachment HTTPS connection unavailable") from failure


def open_public_attachment(url: str) -> PinnedAttachmentResponse:
    """Read one public HTTPS response with max 5 cross-host redirects.

    Proxy is reselected per-hop, and every redirect is separately verified.
    Credentials are sent only in HTTP proxy CONNECT, never to the target.
    """
    for _ in range(6):
        endpoint = validate_public_attachment_url(url)
        connection = _PinnedTLSConnection(endpoint, _trusted_proxy(endpoint))
        path = endpoint.uri.path or "/"
        if endpoint.uri.query:
            path += "?" + endpoint.uri.query
        try:
            connection.request(
                "GET", path, headers={"User-Agent": "mcp-bridge/0.1 workspace-ingress"}
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                response.close()
                connection.close()
                if not location:
                    raise WorkspaceFileError("attachment redirect missing Location")
                url = urllib.parse.urljoin(url, location)
                continue
            if not 200 <= response.status < 300:
                response.close()
                raise WorkspaceFileError(f"attachment HTTPS status {response.status}")
            return PinnedAttachmentResponse(url, connection, response)
        except BaseException:
            connection.close()
            raise
    raise WorkspaceFileError("attachment exceeded HTTPS redirect limit")
