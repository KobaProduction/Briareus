"""Local Compose HTTPS dial override; issuer, SNI and CA checks stay unchanged."""

import http.client
import socket
import ssl
from urllib.parse import urlsplit

from authorization.domain.rauthy import RauthyKeysUnavailable


class LocalIssuerConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(host, timeout=timeout, context=context)
        self._tls_context = context

    def connect(self) -> None:
        raw = socket.create_connection(("local-tls", 443), timeout=self.timeout)
        try:
            self.sock = self._tls_context.wrap_socket(raw, server_hostname="127.0.0.1")
        except BaseException:
            raw.close()
            raise


def fetch_local_issuer(url: str, maximum: int) -> bytes:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "127.0.0.1"
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"/auth/v1/.well-known/openid-configuration", "/auth/v1/oidc/certs"}
    ):
        raise RauthyKeysUnavailable("Unexpected local issuer resource")
    client = LocalIssuerConnection("127.0.0.1", timeout=3, context=ssl.create_default_context())
    try:
        client.request("GET", parsed.path, headers={"Accept": "application/json"})
        response = client.getresponse()
        if response.status != 200 or response.headers.get_content_type() not in {
            "application/json",
            "application/jwk-set+json",
        }:
            raise RauthyKeysUnavailable("Local issuer response rejected")
        raw = response.read(maximum + 1)
        if len(raw) > maximum:
            raise RauthyKeysUnavailable("Local issuer response too large")
        return raw
    except (OSError, ValueError, http.client.HTTPException):
        raise RauthyKeysUnavailable("Verified local issuer TLS unavailable") from None
    finally:
        client.close()
