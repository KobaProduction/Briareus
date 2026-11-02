from __future__ import annotations

import http.client
import ssl
import urllib.parse
from pathlib import Path

from pydantic import BaseModel, ValidationError

from service_runtime.http_transport import (
    HttpTransportError,
    HttpTransportResponse,
    PooledHttpTransport,
)
from service_runtime.providers.tls import provider_ssl_context

from .errors import GitLabError
from .models import GitLabProfile
from .transport_views import (
    GitLabAcknowledgement,
    GitLabModelResponse,
    GitLabPagination,
    GitLabRequestHeaders,
)


def _query_value_text(value: str | int | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class GitLabApiClient:
    def __init__(
        self,
        profile: GitLabProfile,
        *,
        max_connections: int = 4,
        protected_branches: frozenset[str] = frozenset(),
        workspace_root: Path = Path("/workspace"),
        anonymous_only: bool = False,
    ) -> None:
        self.profile = profile
        self.max_connections = max(1, int(max_connections))
        self.protected_branches = protected_branches
        self.workspace_root = workspace_root
        self.anonymous_only = anonymous_only
        parsed = urllib.parse.urlsplit(profile.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise GitLabError(f"account {profile.account_id!r} has invalid base_url")
        self._scheme = parsed.scheme
        self._hostname = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._transport = PooledHttpTransport(
            self._new_connection,
            max_connections=self.max_connections,
            span_name="provider.gitlab.http",
            provider="gitlab",
            acquire_timeout=45,
        )

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self._scheme != "https":
            return None
        return provider_ssl_context(
            verify_tls=self.profile.verify_tls,
            ca_cert_pem=self.profile.ca_cert_pem,
        )

    def _headers(
        self,
        has_body: bool = False,
        *,
        anonymous: bool = False,
    ) -> GitLabRequestHeaders:
        headers = [("Accept", "application/json"), ("User-Agent", "mcp-bridge-gitlab")]
        if not anonymous:
            token = self.profile.token()
            if self.profile.auth_type == "private_token":
                headers.append(("PRIVATE-TOKEN", token))
            elif self.profile.auth_type == "bearer":
                headers.append(("Authorization", f"Bearer {token}"))
            else:
                headers.append(("JOB-TOKEN", token))
        if has_body:
            headers.append(("Content-Type", "application/json"))
        return GitLabRequestHeaders(tuple(headers))

    def _target(
        self,
        path: str,
        query: BaseModel | None = None,
    ) -> str:
        if not path.startswith("/"):
            raise GitLabError("GitLab API path must start with /")
        pairs: list[tuple[str, str]] = []
        values_by_name = (
            query.model_dump(exclude_none=True, by_alias=True) if query is not None else {}
        )
        for key, raw in values_by_name.items():
            if raw is None:
                continue
            values = raw if isinstance(raw, list) else [raw]
            pairs.extend((key, _query_value_text(value)) for value in values)
        encoded = urllib.parse.urlencode(pairs, doseq=True)
        return self._base_path + "/api/v4" + path + (f"?{encoded}" if encoded else "")

    def _url(
        self,
        path: str,
        query: BaseModel | None = None,
    ) -> str:
        return self.profile.base_url.rstrip("/") + self._target(path, query)

    def _new_connection(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._hostname,
                self._port,
                timeout=45,
                context=self._ssl_context(),
            )
        return http.client.HTTPConnection(
            self._hostname,
            self._port,
            timeout=45,
        )

    def _error_message(self, status: int, target: str, data: str) -> str:
        detail = data[:4096]
        if status == 401:
            return (
                f"GitLab authentication failed for profile {self.profile.account_id!r} "
                f"(HTTP 401); check its {self.profile.auth_type} credential"
            )
        if status == 403:
            return (
                f"GitLab denied the operation for profile {self.profile.account_id!r} "
                f"(HTTP 403); check token scopes, project membership, and role: {detail}"
            )
        if status == 429:
            return (
                f"GitLab rate limit exceeded for profile {self.profile.account_id!r} "
                f"(HTTP 429) on {target}"
            )
        return f"GitLab API HTTP {status}: {detail}"

    def _request_transport(
        self,
        method: str,
        path: str,
        *,
        query: BaseModel | None = None,
        payload: BaseModel | None = None,
        allowed_errors: set[int] | None = None,
        allow_public_fallback: bool = True,
    ) -> HttpTransportResponse:
        body = (
            None
            if payload is None
            else payload.model_dump_json(exclude_none=True, by_alias=True).encode("utf-8")
        )
        target = self._target(path, query)
        normalized_method = method.upper()
        if self.anonymous_only and normalized_method not in {"GET", "HEAD"}:
            raise GitLabError("public GitLab access is read-only")
        try:
            response = self._transport.request(
                normalized_method,
                target,
                body=body,
                headers=dict(
                    self._headers(has_body=body is not None, anonymous=self.anonymous_only).fields
                ),
            )
        except HttpTransportError as exc:
            raise GitLabError(
                f"GitLab API transport error for profile {self.profile.account_id!r}: {exc}"
            ) from exc
        status, raw = response.status, response.body
        if (
            allow_public_fallback
            and status in {401, 403, 404}
            and normalized_method in {"GET", "HEAD"}
            and not (allowed_errors and status in allowed_errors)
        ):
            try:
                public_response = self._transport.request(
                    normalized_method,
                    target,
                    body=body,
                    headers=dict(self._headers(has_body=body is not None, anonymous=True).fields),
                )
            except HttpTransportError:
                public_response = None
            if public_response is not None and public_response.status < 400:
                return public_response
        if status >= 400 and not (allowed_errors and status in allowed_errors):
            raise GitLabError(self._error_message(status, target, raw.decode("utf-8", "replace")))
        return response

    def request_model[T: BaseModel](
        self,
        method: str,
        path: str,
        *,
        response_type: type[T],
        query: BaseModel | None = None,
        payload: BaseModel | None = None,
    ) -> GitLabModelResponse[T]:
        response = self._request_transport(method, path, query=query, payload=payload)
        try:
            data = response_type.model_validate_json(response.body)
        except ValidationError as exc:
            raise GitLabError("GitLab returned an invalid response schema") from exc
        return GitLabModelResponse(
            response.status, data, GitLabPagination.from_headers(response.headers)
        )

    def inspect_model[T: BaseModel](
        self,
        path: str,
        *,
        response_type: type[T],
        unavailable_statuses: set[int],
        query: BaseModel | None = None,
    ) -> T | None:
        response = self._request_transport(
            "GET", path, query=query, allowed_errors=unavailable_statuses
        )
        if response.status in unavailable_statuses:
            return None
        try:
            return response_type.model_validate_json(response.body)
        except ValidationError as exc:
            raise GitLabError("GitLab returned an invalid inspection schema") from exc

    def request_ack(
        self, method: str, path: str, *, payload: BaseModel | None = None
    ) -> GitLabAcknowledgement:
        response = self._request_transport(method, path, payload=payload)
        return GitLabAcknowledgement(response.status)

    def request_text(self, method: str, path: str) -> GitLabModelResponse[str]:
        response = self._request_transport(method, path, allow_public_fallback=False)
        return GitLabModelResponse(
            response.status,
            response.body.decode("utf-8", "replace"),
            GitLabPagination.from_headers(response.headers),
        )

    @staticmethod
    def project_selector(project: str | int) -> str:
        value = str(project).strip()
        if not value:
            raise GitLabError("project must be a numeric id or path_with_namespace")
        return urllib.parse.quote(value, safe="")
