"""The only admitted provider transport is HTTPS through the Node egress proxy."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

_DENIED = "Approved HTTPS provider and public-only Node egress proxy required"


@dataclass(frozen=True)
class ProviderTunnel:
    target_host: str
    proxy_host: str = "module-egress"
    proxy_port: int = 8080

    def __post_init__(self) -> None:
        if not self.target_host or self.proxy_host != "module-egress" or self.proxy_port != 8080:
            raise ValueError(_DENIED)

    @classmethod
    def admit(cls, base_url: str, proxy_url: str, *, verify_tls: bool) -> ProviderTunnel:
        target = urlsplit(base_url)
        proxy = urlsplit(proxy_url)
        if not verify_tls or target.scheme != "https" or not target.hostname:
            raise ValueError(_DENIED)
        if (
            target.port not in (None, 443)
            or target.username
            or target.password
            or target.fragment
            or target.query
        ):
            raise ValueError(_DENIED)
        if proxy.scheme != "http" or proxy.hostname != "module-egress" or proxy.port != 8080:
            raise ValueError(_DENIED)
        if proxy.username or proxy.password or proxy.path not in ("", "/"):
            raise ValueError(_DENIED)
        return cls(target.hostname)
