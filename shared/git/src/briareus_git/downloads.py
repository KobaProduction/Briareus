"""Bounded anonymous downloads from provider-issued public HTTPS URLs."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit


class DownloadError(RuntimeError):
    pass


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a checked literal IP while retaining TLS hostname verification."""

    def __init__(self, host: str, address: str) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(host, port=443, timeout=30, context=self.tls_context)
        self.address = address

    def connect(self) -> None:
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _public_connection(url: str) -> tuple[http.client.HTTPSConnection, str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise DownloadError("download redirect must be a public HTTPS URL")
    addresses = {
        str(item[4][0])
        for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    }
    ips = [ipaddress.ip_address(address) for address in addresses]
    if not ips or not all(
        ip.is_global and not ip.is_multicast and not ip.is_reserved for ip in ips
    ):
        raise DownloadError("download redirect resolved to a non-public address")
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    return _PinnedHTTPSConnection(
        parsed.hostname, min(addresses, key=lambda address: (":" in address, address))
    ), target


def read_bounded(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise DownloadError(f"download exceeds MCP limit of {max_bytes} bytes")
    return data


def download_public_https(url: str, max_bytes: int, *, max_redirects: int = 3) -> bytes:
    """Follow only public HTTPS redirects without credentials or DNS re-resolution."""
    if not 1 <= max_bytes <= 16 * 1024 * 1024:
        raise DownloadError("download limit must be between 1 and 16777216 bytes")
    for _ in range(max_redirects + 1):
        try:
            connection, target = _public_connection(url)
            try:
                connection.request("GET", target, headers={"User-Agent": "briareus"})
                response = connection.getresponse()
                if response.status == 200:
                    return read_bounded(response, max_bytes)
                location = response.getheader("Location")
                if response.status not in {301, 302, 303, 307, 308} or not location:
                    raise DownloadError(f"download endpoint returned HTTP {response.status}")
                url = urljoin(url, location)
            finally:
                connection.close()
        except (OSError, http.client.HTTPException, ValueError):
            # Never disclose signed URLs or their query strings.
            raise DownloadError("public HTTPS download failed") from None
    raise DownloadError("download exceeded redirect limit")
