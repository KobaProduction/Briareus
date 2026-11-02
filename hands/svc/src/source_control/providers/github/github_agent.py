from __future__ import annotations

import base64
import http.client
import ssl
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import jwt
from pydantic import BaseModel, ValidationError

from service_runtime.http_transport import (
    HttpTransportError,
    HttpTransportResponse,
    PooledHttpTransport,
)
from service_runtime.repository_checkout import checkout_repository

from .domain.credentials import InstallationCredential
from .domain.repository import RepositoryMetadata
from .infrastructure.cache import CachedRepositoryMetadata
from .infrastructure.schemas.installation import (
    InstallationReference,
    InstallationReferences,
    InstallationTokenReply,
)
from .infrastructure.schemas.rate_limits import ProviderRateLimits
from .infrastructure.schemas.repository import (
    InstallationRepositoryRecords,
    RepositoryRecord,
    RepositoryRecords,
)
from .infrastructure.schemas.requests import GitHubRequestBody
from .local_git_views import GitHubCheckout
from .provider_views import (
    AccessibleRepository,
    RateLimitObservation,
    RateLimitStatus,
    RefreshedRateLimits,
    RepositoryList,
    RepositoryStatus,
)
from .transport_views import (
    GitHubAcknowledgement,
    GitHubModelResponse,
    GitHubPagination,
)

_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2026-03-10"


class GitHubAgentError(RuntimeError):
    """Raised when the GitHub App backend cannot complete a request."""


@dataclass
class GitHubAppClient:
    app_id: str = ""
    private_key: str = field(default="", repr=False)
    account_id: str = ""
    token: str = field(default="", repr=False)
    auth_type: str = "github_app"
    public_only: bool = False
    _installation_ids: dict[str, int] = field(default_factory=dict)
    _tokens: dict[int, InstallationCredential] = field(default_factory=dict, repr=False)
    repository_cache_ttl_seconds: float = 30.0
    max_connections: int = 8
    workspace_root: Path = Path("/workspace")
    protected_branches: frozenset[str] = frozenset({"main", "master"})
    required_checks: tuple[str, ...] = ("test", "docker")
    required_reviewers: tuple[str, ...] = ()
    _transport: PooledHttpTransport = field(init=False, repr=False)
    _cache_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _credential_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _repository_cache: dict[str, CachedRepositoryMetadata] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    public_reader_account: str = ""
    _rate_limit_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _rate_limits: dict[str, RateLimitObservation] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._transport = PooledHttpTransport(
            lambda: http.client.HTTPSConnection(
                "api.github.com",
                timeout=30,
                context=ssl.create_default_context(),
            ),
            max_connections=self.max_connections,
            acquire_timeout=30,
            span_name="provider.github.http",
            provider="github",
        )

    def _assert_allowed(self, repository: str) -> str:
        """Validate a repository selector; GitHub installation scope is the access policy."""
        repository = repository.strip()
        owner, separator, name = repository.partition("/")
        if separator != "/" or not owner or not name or "/" in name:
            raise GitHubAgentError("repository must be owner/name")
        return repository

    def _app_jwt(self) -> str:
        app_id = self.app_id.strip()
        if not app_id.isdigit() or int(app_id) <= 0:
            raise GitHubAgentError(
                f"GitHub APP_ID must be a positive numeric App ID; got {app_id!r}"
            )

        now = int(time.time())
        try:
            token = jwt.encode(
                {
                    "iat": now - 60,
                    "exp": now + 9 * 60,
                    "iss": app_id,
                },
                self.private_key,
                algorithm="RS256",
            )
        except Exception as exc:
            raise GitHubAgentError(
                "GitHub App PRIVATE_KEY_PEM is not a usable RSA private key; "
                "check that the PEM belongs to the configured APP_ID and was not "
                "stored as base64 or truncated text"
            ) from exc
        return str(token)

    @staticmethod
    def _request_target(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise GitHubAgentError("GitHub API request must target https://api.github.com")
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        return target

    @staticmethod
    def _header_int(headers: dict[str, str], name: str) -> int | None:
        raw = headers.get(name)
        if raw is None or not raw.strip():
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _record_rate_limit(
        self,
        headers: dict[str, str],
        *,
        status: int,
        auth_mode: str,
    ) -> RateLimitObservation | None:
        normalized = {key.casefold(): value for key, value in headers.items()}
        resource = normalized.get("x-ratelimit-resource", "core").strip() or "core"
        limit = self._header_int(normalized, "x-ratelimit-limit")
        remaining = self._header_int(normalized, "x-ratelimit-remaining")
        used = self._header_int(normalized, "x-ratelimit-used")
        reset_epoch = self._header_int(normalized, "x-ratelimit-reset")
        retry_after = self._header_int(normalized, "retry-after")
        if all(value is None for value in (limit, remaining, used, reset_epoch, retry_after)):
            return None
        now = int(time.time())
        reset_at = ""
        reset_in_seconds: int | None = None
        if reset_epoch is not None:
            reset_at = datetime.fromtimestamp(reset_epoch, tz=UTC).isoformat()
            reset_in_seconds = max(0, reset_epoch - now)
        snapshot: RateLimitObservation = RateLimitObservation(
            resource=resource,
            auth_mode=auth_mode,
            http_status=status,
            limit=limit,
            remaining=remaining,
            used=used,
            reset_epoch=reset_epoch,
            reset_at=reset_at,
            reset_in_seconds=reset_in_seconds,
            retry_after_seconds=retry_after,
            observed_at=datetime.now(tz=UTC).isoformat(),
        )
        with self._rate_limit_lock:
            self._rate_limits[f"{auth_mode}:{resource}"] = snapshot
        return snapshot

    def rate_limit_status(self) -> RateLimitStatus:
        with self._rate_limit_lock:
            entries = list(self._rate_limits.values())
        entries.sort(
            key=lambda item: (
                item.auth_mode,
                item.resource,
            )
        )
        return RateLimitStatus(
            auth_type=self.auth_type,
            public_only=self.public_only,
            public_reader_account=self.public_reader_account,
            entries=entries,
        )

    @staticmethod
    def _rate_limit_error_message(rate_limit: RateLimitObservation) -> str:
        resource = str(rate_limit.resource or "core")
        auth_mode = str(rate_limit.auth_mode or "unknown")
        remaining = rate_limit.remaining
        reset_at = str(rate_limit.reset_at or "")
        retry_after = rate_limit.retry_after_seconds
        pieces = [
            f"resource={resource}",
            f"auth_mode={auth_mode}",
            f"remaining={remaining if remaining is not None else 'unknown'}",
        ]
        if reset_at:
            pieces.append(f"reset_at={reset_at}")
        if retry_after is not None:
            pieces.append(f"retry_after_seconds={retry_after}")
        return ", ".join(pieces)

    @classmethod
    def _github_error_message(
        cls,
        status: int,
        url: str,
        data: bytes,
        rate_limit: RateLimitObservation | None = None,
    ) -> str:
        detail = data[:4096].decode("utf-8", "replace")
        path = urllib.parse.urlsplit(url).path
        rate = rate_limit
        rate_text = cls._rate_limit_error_message(rate) if rate else ""
        detail_casefold = detail.casefold()
        if status == 401:
            if (
                path == "/app"
                or path.endswith("/installation")
                or (path.startswith("/app/installations/") and path.endswith("/access_tokens"))
            ):
                return (
                    "GitHub App authentication failed (HTTP 401); check that APP_ID "
                    "matches PRIVATE_KEY_PEM and that the GitHub App private key is active"
                )
            return (
                "GitHub installation authentication failed (HTTP 401); the installation "
                "token may be expired/revoked or the App installation may have changed"
            )
        if status in {403, 429} and (
            (rate is not None and rate.remaining == 0)
            or (rate is not None and rate.retry_after_seconds is not None)
            or "rate limit" in detail_casefold
        ):
            suffix = f" ({rate_text})" if rate_text else ""
            return f"GitHub API rate limit exceeded (HTTP {status}) for {path}{suffix}: {detail}"
        if status == 403:
            return (
                "GitHub API denied the operation (HTTP 403); check GitHub App repository "
                f"permissions for {path}: {detail}"
            )
        return f"GitHub API HTTP {status}: {detail}"

    def _observe_response(self, response: HttpTransportResponse) -> None:
        """Owner adapters can retain native response metadata before error handling."""
        del response

    def _request_transport(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        payload: BaseModel | None = None,
        allowed_errors: set[int] | None = None,
        auth_mode: str = "",
    ) -> HttpTransportResponse:
        body = (
            None
            if payload is None
            else payload.encode_http_body()
            if isinstance(payload, GitHubRequestBody)
            else payload.model_dump_json(exclude_none=True, by_alias=True).encode("utf-8")
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mcp-bridge",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"

        target = self._request_target(url)
        normalized_method = method.upper()
        try:
            response = self._transport.request(
                normalized_method,
                target,
                body=body,
                headers=headers,
                reconnect_retries=6 if normalized_method in {"GET", "HEAD"} else 1,
                retry_backoff_seconds=0.25 if normalized_method in {"GET", "HEAD"} else 0.0,
            )
        except HttpTransportError as exc:
            raise GitHubAgentError(f"GitHub API transport error: {exc}") from exc

        self._observe_response(response)
        status = response.status
        data = response.body
        effective_auth_mode = auth_mode or ("authenticated" if token else "anonymous")
        rate_limit = self._record_rate_limit(
            response.headers,
            status=status,
            auth_mode=effective_auth_mode,
        )
        if status >= 400 and not (allowed_errors and status in allowed_errors):
            raise GitHubAgentError(self._github_error_message(status, url, data, rate_limit))
        return response

    def _installation_id(self, repository: str) -> int:
        repository = self._assert_allowed(repository)
        key = repository.casefold()
        cached = self._installation_ids.get(key)
        if cached is not None:
            return cached
        with self._credential_lock:
            cached = self._installation_ids.get(key)
            if cached is not None:
                return cached
            result = self._request_inspect_model(
                "GET",
                f"{_GITHUB_API}/repos/{repository}/installation",
                response_type=InstallationReference,
                token=self._app_jwt(),
                unavailable_statuses={404},
                auth_mode="github_app_jwt",
            )
            if result is None:
                raise GitHubAgentError(
                    f"repository {repository!r} is not installed for GitHub App "
                    f"{self.app_id}; add it to the App installation or use the correct App"
                )
            self._installation_ids[key] = result.id
            return result.id

    def _installation_token_for_id(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached is not None and cached.reusable_at(time.time()):
            return cached.token
        with self._credential_lock:
            cached = self._tokens.get(installation_id)
            if cached is not None and cached.reusable_at(time.time()):
                return cached.token
            result = self._request_model(
                "POST",
                f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
                response_type=InstallationTokenReply,
                token=self._app_jwt(),
                auth_mode="github_app_jwt",
            ).data
            credential = InstallationCredential(
                result.token.get_secret_value(), result.expires_at.timestamp()
            )
            self._tokens[installation_id] = credential
            return credential.token

    def _installation_token(self, repository: str) -> str:
        if self.token:
            self._assert_allowed(repository)
            return self.token
        return self._installation_token_for_id(self._installation_id(repository))

    def _any_installation_token(self) -> str:
        now = time.time()
        for cached in list(self._tokens.values()):
            if cached.reusable_at(now):
                return cached.token
        installation_ids = self._installation_ids_from_github()
        if not installation_ids:
            raise GitHubAgentError(
                "GitHub App has no installations; authenticated App identity lookup is unavailable"
            )
        return self._installation_token_for_id(installation_ids[0])

    def _assert_public_repository(self, repository: str) -> None:
        key = repository.casefold()
        now = time.monotonic()
        if self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                cached = self._repository_cache.get(key)
                if cached is not None and cached.valid_at(now):
                    if cached.metadata.private:
                        raise GitHubAgentError(
                            "public GitHub access cannot read private repositories"
                        )
                    return
        result = self._request_model(
            "GET",
            f"{_GITHUB_API}/repos/{repository}",
            response_type=RepositoryRecord,
            token=self.token or None,
            auth_mode="public_reader" if self.token else "public_anonymous",
        ).data
        if result.private:
            raise GitHubAgentError("public GitHub access cannot read private repositories")
        self._remember_repository(key, result)

    def _outside_installation_response(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: BaseModel | None,
        allowed_errors: set[int] | None,
        cause: GitHubAgentError,
    ) -> HttpTransportResponse:
        del method, path, payload, allowed_errors
        raise GitHubAgentError(
            f"repository {repository!r} is outside this GitHub App installation; "
            "use account_id='public' for authenticated read-only public access"
        ) from cause

    def _repo_transport(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: BaseModel | None = None,
        allowed_errors: set[int] | None = None,
    ) -> HttpTransportResponse:
        repository = self._assert_allowed(repository)
        normalized_method = method.upper()
        if self.public_only:
            if normalized_method not in {"GET", "HEAD"}:
                raise GitHubAgentError("public GitHub access is read-only")
            if path.split("?", 1)[0] != f"/repos/{repository}":
                self._assert_public_repository(repository)
            return self._request_transport(
                normalized_method,
                f"{_GITHUB_API}{path}",
                token=self.token or None,
                payload=payload,
                allowed_errors=allowed_errors,
                auth_mode="public_reader" if self.token else "public_anonymous",
            )
        if self.token:
            return self._request_transport(
                normalized_method,
                f"{_GITHUB_API}{path}",
                token=self.token,
                payload=payload,
                allowed_errors=allowed_errors,
                auth_mode="user_token",
            )
        try:
            token = self._installation_token(repository)
        except GitHubAgentError as exc:
            if normalized_method in {"GET", "HEAD"} and "is not installed for GitHub App" in str(
                exc
            ):
                return self._outside_installation_response(
                    repository,
                    normalized_method,
                    path,
                    payload=payload,
                    allowed_errors=allowed_errors,
                    cause=exc,
                )
            raise
        return self._request_transport(
            normalized_method,
            f"{_GITHUB_API}{path}",
            token=token,
            payload=payload,
            allowed_errors=allowed_errors,
            auth_mode="installation",
        )

    def _repo_model[T: BaseModel](
        self,
        repository: str,
        method: str,
        path: str,
        *,
        response_type: type[T],
        payload: BaseModel | None = None,
        query: BaseModel | None = None,
    ) -> GitHubModelResponse[T]:
        if query is not None:
            path += ("&" if "?" in path else "?") + urllib.parse.urlencode(
                query.model_dump(exclude_none=True, by_alias=True), doseq=True
            )
        response = self._repo_transport(repository, method, path, payload=payload)
        return self._typed_response(response, response_type)

    @staticmethod
    def _typed_response[T: BaseModel](
        response: HttpTransportResponse, response_type: type[T]
    ) -> GitHubModelResponse[T]:
        try:
            data = response_type.model_validate_json(response.body)
        except ValidationError as exc:
            raise GitHubAgentError("GitHub returned an invalid response schema") from exc
        link = next(
            (value for key, value in response.headers.items() if key.casefold() == "link"), ""
        )
        return GitHubModelResponse(response.status, data, GitHubPagination.from_link(link))

    def _request_model[T: BaseModel](
        self,
        method: str,
        url: str,
        *,
        response_type: type[T],
        token: str | None = None,
        payload: BaseModel | None = None,
        auth_mode: str = "",
    ) -> GitHubModelResponse[T]:
        response = self._request_transport(
            method, url, token=token, payload=payload, auth_mode=auth_mode
        )
        return self._typed_response(response, response_type)

    def _request_inspect_model[T: BaseModel](
        self,
        method: str,
        url: str,
        *,
        response_type: type[T],
        unavailable_statuses: set[int],
        token: str | None = None,
        auth_mode: str = "",
    ) -> T | None:
        response = self._request_transport(
            method, url, token=token, auth_mode=auth_mode, allowed_errors=unavailable_statuses
        )
        if response.status in unavailable_statuses:
            return None
        return self._typed_response(response, response_type).data

    def _repo_inspect_model[T: BaseModel](
        self,
        repository: str,
        method: str,
        path: str,
        *,
        response_type: type[T],
        unavailable_statuses: set[int],
    ) -> T | None:
        response = self._repo_transport(
            repository, method, path, allowed_errors=unavailable_statuses
        )
        if response.status in unavailable_statuses:
            return None
        try:
            return response_type.model_validate_json(response.body)
        except ValidationError as exc:
            raise GitHubAgentError("GitHub returned an invalid inspection schema") from exc

    def _repo_ack(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: BaseModel | None = None,
    ) -> GitHubAcknowledgement:
        response = self._repo_transport(repository, method, path, payload=payload)
        return GitHubAcknowledgement(response.status)

    @staticmethod
    def _git_authorization_header(token: str) -> str:
        if not token:
            return ""
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
        return f"Authorization: Basic {encoded}"

    def _checkout_repository(
        self,
        repository: str,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> GitHubCheckout:
        repository = self._assert_allowed(repository)
        token = ""
        if self.public_only:
            self._assert_public_repository(repository)
        if self.public_only or self.token:
            token = self.token
        else:
            try:
                token = self._installation_token(repository)
            except GitHubAgentError as exc:
                if "is not installed for GitHub App" not in str(exc):
                    raise
        result = checkout_repository(
            f"https://github.com/{repository}.git",
            destination,
            workspace_root=self.workspace_root,
            mode=mode,
            ref=ref,
            overwrite=overwrite,
            auth_scope="https://github.com/",
            auth_header=self._git_authorization_header(token),
            fallback_without_auth=False,
        )
        return GitHubCheckout(
            path=result.path,
            resolved_path=result.resolved_path,
            mode=result.mode,
            ref=result.ref,
            git_metadata=result.git_metadata,
            auth_mode=result.auth_mode,
            repository=repository,
        )

    def _installation_ids_from_github(self) -> list[int]:
        installation_ids: list[int] = []
        page = 1
        while True:
            result = self._request_model(
                "GET",
                f"{_GITHUB_API}/app/installations?per_page=100&page={page}",
                response_type=InstallationReferences,
                token=self._app_jwt(),
                auth_mode="github_app_jwt",
            ).data.root
            installation_ids.extend(item.id for item in result)
            if len(result) < 100:
                break
            page += 1
        return installation_ids

    def _app_repositories(self) -> list[AccessibleRepository]:
        app_repositories: list[AccessibleRepository] = []
        seen: set[str] = set()
        for installation_id in self._installation_ids_from_github():
            token = self._installation_token_for_id(installation_id)
            page = 1
            while True:
                items = self._request_model(
                    "GET",
                    f"{_GITHUB_API}/installation/repositories?per_page=100&page={page}",
                    response_type=InstallationRepositoryRecords,
                    token=token,
                    auth_mode="installation",
                ).data.repositories
                for item in items:
                    if item.full_name.casefold() in seen:
                        continue
                    seen.add(item.full_name.casefold())
                    self._installation_ids[item.full_name.casefold()] = installation_id
                    app_repositories.append(
                        AccessibleRepository(
                            full_name=item.full_name,
                            private=item.private,
                            default_branch=item.default_branch or "",
                            archived=item.archived,
                            fork=item.fork,
                            permissions=item.permissions,
                            installation_id=installation_id,
                        )
                    )
                if len(items) < 100:
                    break
                page += 1
        app_repositories.sort(key=lambda item: item.full_name.casefold())
        return app_repositories

    def list_repositories(self) -> RepositoryList:
        if self.token:
            token_repositories: list[AccessibleRepository] = []
            page = 1
            while True:
                result = self._request_model(
                    "GET",
                    (
                        f"{_GITHUB_API}/user/repos?"
                        "affiliation=owner,collaborator,organization_member"
                        f"&per_page=100&page={page}"
                    ),
                    response_type=RepositoryRecords,
                    token=self.token,
                    auth_mode="user_token",
                ).data.root
                token_repositories.extend(
                    AccessibleRepository(
                        full_name=item.full_name,
                        private=item.private,
                        default_branch=item.default_branch or "",
                        archived=item.archived,
                        fork=item.fork,
                        permissions=item.permissions,
                    )
                    for item in result
                )
                if len(result) < 100:
                    break
                page += 1
            token_repositories.sort(key=lambda item: item.full_name.casefold())
            return RepositoryList(
                auth_type=self.auth_type,
                count=len(token_repositories),
                repositories=token_repositories,
            )
        app_repositories = self._app_repositories()
        return RepositoryList(
            auth_type=self.auth_type,
            app_id=self.app_id,
            count=len(app_repositories),
            repositories=app_repositories,
        )

    def refresh_rate_limits(self, repository: str = "") -> RefreshedRateLimits:
        token = ""
        auth_mode = "anonymous"
        access_mode = "public_anonymous"
        if self.public_only:
            token = self.token
            auth_mode = "public_reader" if token else "public_anonymous"
            access_mode = "public_authenticated" if token else "public_anonymous"
        elif self.token:
            token = self.token
            auth_mode = "user_token"
            access_mode = "user_token"
        else:
            token = (
                self._installation_token(repository)
                if repository.strip()
                else self._any_installation_token()
            )
            auth_mode = "installation"
            access_mode = "installation"
        payload = self._request_model(
            "GET",
            f"{_GITHUB_API}/rate_limit",
            response_type=ProviderRateLimits,
            token=token or None,
            auth_mode=auth_mode,
        ).data
        return RefreshedRateLimits(
            account_id=self.account_id,
            auth_type=self.auth_type,
            access_mode=access_mode,
            repository=repository.strip(),
            public_reader_account=self.public_reader_account,
            provider=payload,
            observed=self.rate_limit_status().entries,
        )

    def _repository_metadata(
        self,
        repository: str,
        *,
        refresh: bool = False,
    ) -> RepositoryMetadata:
        repository = self._assert_allowed(repository)
        key = repository.casefold()
        now = time.monotonic()
        if not refresh and self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                cached = self._repository_cache.get(key)
                if cached is not None and cached.valid_at(now):
                    return cached.metadata
        result = self._repo_model(
            repository, "GET", f"/repos/{repository}", response_type=RepositoryRecord
        ).data
        return self._remember_repository(key, result)

    def status(self, repository: str) -> RepositoryStatus:
        repository = self._assert_allowed(repository)
        result = self._repository_metadata(repository)
        response: RepositoryStatus = RepositoryStatus(
            repository=str(result.repository),
            default_branch=str(result.default_branch),
            private=bool(result.private),
            auth_type=self.auth_type,
            status="ok",
        )
        if self.public_only:
            response.auth_type = "public"
            response.access_mode = "public_authenticated" if self.token else "public_anonymous"
            response.public_reader_account = self.public_reader_account
            response.rate_limits = self.rate_limit_status()
            return response
        if self.token:
            response.access_mode = "user_token"
            response.rate_limits = self.rate_limit_status()
            return response
        response.app_id = self.app_id
        response.installation_id = self._installation_id(repository)
        response.access_mode = "installation"
        response.rate_limits = self.rate_limit_status()
        return response

    def _remember_repository(self, key: str, record: RepositoryRecord) -> RepositoryMetadata:
        metadata = RepositoryMetadata(
            record.full_name,
            record.default_branch or "",
            record.private,
            record.archived,
            record.fork,
        )
        if self.repository_cache_ttl_seconds > 0:
            with self._cache_lock:
                self._repository_cache[key] = CachedRepositoryMetadata(
                    time.monotonic() + self.repository_cache_ttl_seconds, metadata
                )
        return metadata
