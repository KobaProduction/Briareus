"""Provider endpoint and display-name invariants, without HTTP or validation SDKs."""

import re
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import SplitResult, urlsplit


def provider_display_name(value: str) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("display_name must not contain control characters")
    return value


def require_public_dns(host: str) -> None:
    if (
        "." not in host
        or len(host) > 253
        or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".onion"))
    ):
        raise ValueError("provider endpoint requires a public DNS name")
    labels = host.split(".")
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) or len(label) > 63
        for label in labels
    ):
        raise ValueError("invalid provider DNS hostname")
    if not labels[-1].isalpha() or len(labels[-1]) < 2:
        raise ValueError("provider hostname needs a public DNS suffix")


def require_public_host(host: str) -> None:
    try:
        address = ip_address(host)
    except ValueError:
        require_public_dns(host)
    else:
        if not address.is_global:
            raise ValueError("provider endpoint IP is not globally routable")


def require_provider_origin(value: str, parsed: SplitResult) -> None:
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
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        raise ValueError("provider URL contains prohibited characters")
    if "%" in parsed.netloc:
        raise ValueError("encoded host and IPv6 zone identifiers are forbidden")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("invalid provider endpoint port") from None
    if port is not None and port not in {443, 8443}:
        raise ValueError("provider endpoint port is not allowed")


@dataclass(frozen=True)
class ProviderEndpoint:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            return
        parsed = urlsplit(self.value)
        require_provider_origin(self.value, parsed)
        if parsed.hostname is None:
            raise ValueError("provider endpoint requires a hostname")
        require_public_host(parsed.hostname.casefold())
        object.__setattr__(self, "value", self.value.rstrip("/"))
