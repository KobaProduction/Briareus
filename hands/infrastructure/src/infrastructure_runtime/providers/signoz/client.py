from __future__ import annotations

import http as http
import ssl as ssl
import urllib.parse

from pydantic import BaseModel, ValidationError

from infrastructure_runtime.providers.http_connection import ProviderHttpConnection
from service_runtime.account_contracts import AccountConnectionSummary
from service_runtime.account_contracts import ResolvedAccount as ResolvedAccount
from service_runtime.http_transport import (
    HttpTransportError,
    HttpTransportResponse,
)
from service_runtime.provider_identity import SigNozReply, SigNozServiceAccount
from service_runtime.providers.tls import provider_ssl_context as provider_ssl_context

from .domain.search import TelemetrySearch
from .infrastructure.discovery import (
    FieldKeysQuery,
    FieldKeysReply,
    FieldValuesQuery,
    FieldValuesReply,
)
from .infrastructure.query_contracts import QueryRangeRequest, ServicesQuery
from .infrastructure.search_query import search_query


class SigNozClientError(RuntimeError):
    pass


class SigNozClient(ProviderHttpConnection):
    _url_error_type = SigNozClientError
    _url_error_message = "SigNoz base_url must be absolute HTTP(S)"
    _http_span_name = "provider.signoz.http"
    _http_provider = "signoz"

    def _target(self, path: str, query: FieldKeysQuery | None = None) -> str:
        if not path.startswith("/"):
            raise SigNozClientError("SigNoz path must start with /")
        target = self._base_path + path
        if query:
            target += "?" + urllib.parse.urlencode(
                query.model_dump(mode="json", by_alias=True, exclude_none=True)
            )
        return target

    def _request_transport(
        self,
        method: str,
        path: str,
        *,
        query: FieldKeysQuery | None = None,
        payload: QueryRangeRequest | ServicesQuery | None = None,
    ) -> HttpTransportResponse:
        body = (
            None
            if payload is None
            else payload.model_dump_json(by_alias=True, exclude_unset=True).encode()
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "SIGNOZ-API-KEY": self.account.credential,
            "User-Agent": "mcp-bridge-signoz",
        }
        try:
            response = self._transport.request(
                method.upper(),
                self._target(path, query),
                body=body,
                headers=headers,
                reconnect_retries=1,
            )
        except HttpTransportError as exc:
            raise SigNozClientError(f"SigNoz transport error: {exc}") from exc
        if response.status >= 400:
            detail = response.body[:4096].decode("utf-8", "replace")
            raise SigNozClientError(f"SigNoz HTTP {response.status}: {detail}")
        return response

    def _request_model[T: BaseModel](
        self, method: str, path: str, response_type: type[T], *, query: FieldKeysQuery | None = None
    ) -> T:
        response = self._request_transport(method, path, query=query)
        try:
            return response_type.model_validate_json(response.body)
        except ValidationError as exc:
            raise SigNozClientError("SigNoz returned an invalid response schema") from exc

    def whoami(self) -> SigNozReply[SigNozServiceAccount]:
        return self._request_model(
            "GET", "/api/v1/service_accounts/me", SigNozReply[SigNozServiceAccount]
        )

    def query_range(self, payload: QueryRangeRequest) -> HttpTransportResponse:
        return self._request_transport("POST", "/api/v5/query_range", payload=payload)

    def search_logs(
        self,
        *,
        start_ms: int,
        end_ms: int,
        filter_expression: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> HttpTransportResponse:
        search = TelemetrySearch("logs", start_ms, end_ms, filter_expression, limit, offset)
        return self.query_range(search_query(search))

    def search_traces(
        self,
        *,
        start_ms: int,
        end_ms: int,
        filter_expression: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> HttpTransportResponse:
        search = TelemetrySearch("traces", start_ms, end_ms, filter_expression, limit, offset)
        return self.query_range(search_query(search))

    def list_services(self, *, start: str, end: str) -> HttpTransportResponse:
        return self._request_transport(
            "POST",
            "/api/v1/services",
            payload=ServicesQuery(start=start, end=end),
        )

    def field_keys(
        self,
        *,
        signal: str,
        search_text: str = "",
        metric_name: str = "",
    ) -> FieldKeysReply:
        query = FieldKeysQuery(
            signal=signal, search_text=search_text or None, metric_name=metric_name or None
        )
        return self._request_model("GET", "/api/v1/fields/keys", FieldKeysReply, query=query)

    def field_values(
        self,
        *,
        signal: str,
        name: str,
        search_text: str = "",
        metric_name: str = "",
    ) -> FieldValuesReply:
        query = FieldValuesQuery(
            signal=signal,
            name=name,
            search_text=search_text or None,
            metric_name=metric_name or None,
        )
        return self._request_model("GET", "/api/v1/fields/values", FieldValuesReply, query=query)

    def account_summary(self) -> AccountConnectionSummary:
        return AccountConnectionSummary(
            id=self.account.id,
            alias=self.account.alias,
            provider=self.account.provider,
            auth_type=self.account.auth_type,
            base_url=self.account.base_url,
            external_id=self.account.external_id,
            verify_tls=self.account.verify_tls,
            ca_cert_pem=self.account.ca_cert_pem,
            enabled=self.account.enabled,
            created_at=self.account.created_at,
            updated_at=self.account.updated_at,
            credential_configured=True,
        )
