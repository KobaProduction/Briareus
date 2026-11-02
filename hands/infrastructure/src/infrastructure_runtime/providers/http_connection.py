"""Infrastructure provider HTTP connections with the selected account TLS policy."""

from __future__ import annotations

import ssl
import urllib.parse
from typing import ClassVar

from service_runtime.account_contracts import ResolvedAccount
from service_runtime.http_transport import PooledHttpTransport, _HttpConnectionFactory
from service_runtime.providers.tls import provider_ssl_context


class ProviderHttpConnection(_HttpConnectionFactory):
    account: ResolvedAccount
    base_url: str
    _url_error_type: ClassVar[type[RuntimeError]]
    _url_error_message: ClassVar[str]
    _http_span_name: ClassVar[str]
    _http_provider: ClassVar[str]

    def __init__(self, account: ResolvedAccount, *, timeout_seconds: float = 30.0) -> None:
        self.account = account
        self.base_url = account.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise self._url_error_type(self._url_error_message)
        self._scheme = parsed.scheme
        self._hostname = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._transport = PooledHttpTransport(
            self._new_connection,
            max_connections=4,
            acquire_timeout=self.timeout_seconds,
            span_name=self._http_span_name,
            provider=self._http_provider,
        )

    def _context(self) -> ssl.SSLContext | None:
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https":
            return None
        return provider_ssl_context(
            verify_tls=self.account.verify_tls,
            ca_cert_pem=self.account.ca_cert_pem,
        )
