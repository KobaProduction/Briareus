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
    _PinnedRetryTLSSetup as _SharedPinnedTLSSetup,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    _PublicEndpoint as _PublicEndpoint,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    _resolve_addresses as _resolve_addresses,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    _trusted_proxy as _trusted_proxy,
)
from project_runtime_client.files.infrastructure.public_attachment import (
    validate_public_attachment_url as validate_public_attachment_url,
)


class _PinnedTLSConnection(_SharedPinnedTLSSetup):
    def __init__(self, endpoint: _PublicEndpoint, proxy: _EgressProxy | None) -> None:
        host = endpoint.uri.hostname
        if host is None:
            raise WorkspaceFileError("attachment HTTPS host required")
        super().__init__(host, port=endpoint.uri.port or 443, timeout=60)
        self._target_addresses = endpoint.addresses
        self._proxy = proxy



@dataclass(frozen=True, slots=True)
class AttachmentRedirect:
    location: str


def _request_attachment(url: str) -> PinnedAttachmentResponse | AttachmentRedirect:
    endpoint = validate_public_attachment_url(url)
    connection = _PinnedTLSConnection(endpoint, _trusted_proxy(endpoint))
    path = endpoint.uri.path or "/"
    if endpoint.uri.query:
        path += "?" + endpoint.uri.query
    try:
        connection.request("GET", path, headers={"User-Agent": "mcp-bridge/0.1 workspace-ingress"})
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            response.close()
            connection.close()
            if not location:
                raise WorkspaceFileError("attachment redirect missing Location")
            return AttachmentRedirect(urllib.parse.urljoin(url, location))
        if not 200 <= response.status < 300:
            response.close()
            raise WorkspaceFileError(f"attachment HTTPS status {response.status}")
        return PinnedAttachmentResponse(url, connection, response)
    except BaseException:
        connection.close()
        raise


def open_public_attachment(url: str) -> PinnedAttachmentResponse:
    """Read one public HTTPS response with at most five redirects."""
    for _ in range(6):
        result = _request_attachment(url)
        if isinstance(result, AttachmentRedirect):
            url = result.location
            continue
        return result
    raise WorkspaceFileError("attachment exceeded HTTPS redirect limit")
