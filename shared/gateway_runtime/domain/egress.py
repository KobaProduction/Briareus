"""Public egress destinations and the bounded proxy request contract."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class PublicDestination:
    host: str
    port: int

    def __post_init__(self) -> None:
        if not self.host or len(self.host) > 253 or self.port not in {80, 443} or "%" in self.host:
            raise ValueError("Unsupported public destination")


@dataclass(frozen=True, slots=True)
class OutboundRequest:
    destination: PublicDestination
    preface: bytes | None


def public_addresses(addresses: Iterable[str]) -> tuple[str, ...]:
    observed = set(addresses)
    if not observed:
        raise ValueError("Private or mixed DNS destination denied")
    for address in observed:
        parsed = ipaddress.ip_address(address)
        if not parsed.is_global or parsed.is_multicast or parsed.is_reserved:
            raise ValueError("Private or mixed DNS destination denied")
    return tuple(sorted(observed))


def loopback_peer(host: str) -> bool:
    return ipaddress.ip_address(host).is_loopback


def _forward_headers(lines: list[str]) -> tuple[str, ...]:
    forwarded: list[str] = []
    seen: set[str] = set()
    for line in lines:
        name, _value = line.split(":", 1)
        key = name.lower()
        if key in seen or not name or any(character.isspace() for character in name):
            raise ValueError("Invalid proxy header")
        seen.add(key)
        if key in {"content-length", "transfer-encoding", "upgrade"}:
            raise ValueError("HTTP body or upgrade denied")
        if key not in {"host", "connection", "proxy-connection", "proxy-authorization"}:
            forwarded.append(line)
    return tuple(forwarded)


def parse_proxy_header(header: bytes) -> OutboundRequest | None:
    """None denotes the local readiness probe; no remote destination is dialed."""
    if len(header) > 16384:
        raise ValueError("Proxy header too large")
    lines = header.decode("iso-8859-1").split("\r\n")
    method, target, version = lines[0].split(" ")
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ValueError("Unsupported proxy protocol")
    if method == "GET" and target == "/health/ready":
        return None
    if method == "CONNECT":
        url = urlsplit("https://" + target)
        if url.port != 443 or url.path or url.query or url.fragment or url.username or url.password:
            raise ValueError("Exact HTTPS authority required")
        return OutboundRequest(PublicDestination(url.hostname or "", 443), None)
    return _http_read(method, target, lines[1:-2])


def _http_read(method: str, target: str, header_lines: list[str]) -> OutboundRequest:
    url = urlsplit(target)
    if (
        url.scheme != "http"
        or url.port not in {None, 80}
        or url.username
        or url.password
        or method not in {"GET", "HEAD"}
    ):
        raise ValueError("Only public HTTP reads are supported")
    headers = _forward_headers(header_lines)
    path = (url.path or "/") + ("?" + url.query if url.query else "")
    request = (
        method + " " + path + " HTTP/1.1",
        "Host: " + url.netloc,
        "Connection: close",
        *headers,
        "",
        "",
    )
    return OutboundRequest(
        PublicDestination(url.hostname or "", 80), "\r\n".join(request).encode("iso-8859-1")
    )
