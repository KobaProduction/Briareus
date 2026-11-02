"""Provider endpoint invariants, independent of HTTP clients and schemas."""

import re
from ipaddress import ip_address
from urllib.parse import SplitResult, urlsplit


def canonical_endpoint(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    _require_https_endpoint(parsed, value)
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise ValueError("provider URL contains prohibited characters")
    if "%" in parsed.netloc:
        raise ValueError("encoded host and IPv6 zone identifiers are forbidden")
    _require_public_host(parsed.hostname or "")
    _require_allowed_port(parsed)
    return value.rstrip("/")


def _require_https_endpoint(parsed: SplitResult, value: str) -> None:
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(value) > 2048
    ):
        raise ValueError("provider endpoint must be a bare HTTPS origin/path")


def _require_public_host(host: str) -> None:
    host = host.casefold()
    try:
        address = ip_address(host)
    except ValueError:
        _require_public_dns(host)
    else:
        if not address.is_global:
            raise ValueError("provider endpoint IP is not globally routable")


def _require_public_dns(host: str) -> None:
    if (
        "." not in host
        or len(host) > 253
        or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".onion"))
    ):
        raise ValueError("provider endpoint requires a public DNS name")
    labels = host.split(".")
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part) or len(part) > 63
        for part in labels
    ):
        raise ValueError("invalid provider DNS hostname")
    if not labels[-1].isalpha() or len(labels[-1]) < 2:
        raise ValueError("provider hostname needs a public DNS suffix")


def _require_allowed_port(parsed: SplitResult) -> None:
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("invalid provider endpoint port") from None
    if port is not None and port not in {443, 8443}:
        raise ValueError("provider endpoint port is not allowed")
