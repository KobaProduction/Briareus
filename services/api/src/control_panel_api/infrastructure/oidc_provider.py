"""Rauthy HTTP implementation of provider protocol capabilities and local metadata cache."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import partial
from time import monotonic
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, SecretStr, StrictStr, ValidationError

from control_panel_api._local_provider_transport import provider_http_client
from control_panel_api._oidc_id_token import verify_rauthy_id_token
from control_panel_api._oidc_origin_policy import validate_files_resource_intent
from control_panel_api._oidc_refresh import capture_refresh as _capture_refresh
from control_panel_api._oidc_resource import verify_resource_credential
from control_panel_api.application.oidc_provider import AuthenticateOidcCode, CompleteOidcCode
from control_panel_api.application.oidc_provider_contracts import (
    OidcDiscovery,
    PublicOidcConfiguration,
    UnverifiedOidcTokenResponse,
)
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcAuthorizationAttempt,
    OidcIdentityRejected,
    OidcProviderUnavailable,
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
    VerifiedOidcLogin,
    VerifiedRefreshCredential,
)
from control_panel_api.domain.oidc_provider import (
    is_https_url,
    require_code_exchange,
    require_userinfo_bearer,
    require_userinfo_identity,
)
from control_panel_api.infrastructure._oidc_bindings import _OwnedClient
from control_panel_api.infrastructure.json_fields import validate_unique_fields

_utc_now = partial(datetime.now, UTC)


def pkce_s256(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


class ProviderUserInfo(BaseModel):
    sub: StrictStr
    id: StrictStr


def _checked_identity(raw: object) -> VerifiedOidcIdentity:
    if not isinstance(raw, VerifiedOidcIdentity):
        raise OidcIdentityRejected("Rauthy Userinfo signed subject unavailable")
    subject: object = raw.subject
    if not isinstance(subject, str):
        raise OidcIdentityRejected("Rauthy Userinfo signed subject unavailable")
    return raw


def _checked_bearer(raw: object) -> str:
    if not isinstance(raw, str):
        raise OidcIdentityRejected("Rauthy bearer not suitable for Userinfo")
    require_userinfo_bearer(raw)
    return raw


def _require_userinfo_reply(response: httpx.Response, subject: str) -> None:
    if response.status_code in (401, 403):
        raise OidcIdentityRejected("Rauthy Userinfo rejected current user")
    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if (
        response.status_code != 200
        or not 1 <= len(response.content) <= 65536
        or mime != "application/json"
    ):
        raise OidcProviderUnavailable("Rauthy Userinfo response unavailable")
    try:
        validate_unique_fields(response.content)
    except (ValueError, UnicodeDecodeError, TypeError):
        raise OidcIdentityRejected("Rauthy Userinfo response malformed") from None
    try:
        info = ProviderUserInfo.model_validate_json(response.content)
    except ValidationError:
        raise OidcIdentityRejected("Rauthy Userinfo subject mismatch") from None
    if info.sub != subject or info.id != subject:
        raise OidcIdentityRejected("Rauthy Userinfo subject mismatch")


class RauthyOidcAdapter(_OwnedClient):
    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        http_client: httpx.AsyncClient | None = None,
        cache_seconds: float = 300.0,
        resource_audience: str | None = None,
    ) -> None:
        self._issuer, self._client_id = issuer.rstrip("/"), client_id
        validate_files_resource_intent(
            issuer=self._issuer, client_id=client_id, resource_audience=resource_audience
        )
        self._resource_audience = resource_audience
        if not is_https_url(self._issuer) or not client_id or not client_id.strip():
            raise ValueError("OIDC requires a real HTTPS issuer and client ID")
        self._client = http_client or provider_http_client(
            timeout=5.0, follow_redirects=False, trust_env=False
        )
        self._owns_client = http_client is None
        self._cache_seconds = max(1.0, cache_seconds)
        self._cached: OidcDiscovery | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def issuer(self) -> str:
        return self._issuer

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def resource_audience(self) -> str | None:
        return self._resource_audience

    async def discovery(self) -> OidcDiscovery:
        if self._cached is not None and monotonic() < self._expires_at:
            return self._cached
        async with self._lock:
            if self._cached is not None and monotonic() < self._expires_at:
                return self._cached
            metadata = await self._load_discovery()
            metadata.endpoints().require_pinned(self._issuer)
            self._cached = metadata
            self._expires_at = monotonic() + self._cache_seconds
            return metadata

    async def _load_discovery(self) -> OidcDiscovery:
        try:
            response = await self._client.get(
                f"{self._issuer}/.well-known/openid-configuration",
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return OidcDiscovery.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
            raise OidcProviderUnavailable("OIDC issuer discovery unavailable") from exc

    async def prepare_authorization_code(self, *, redirect_uri: str) -> OidcAuthorizationAttempt:
        if not is_https_url(redirect_uri):
            raise ValueError("approved HTTPS OIDC callback required")
        provider = await self.discovery()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": pkce_s256(verifier),
                "code_challenge_method": "S256",
                **({"resource": self._resource_audience} if self._resource_audience else {}),
            }
        )
        return OidcAuthorizationAttempt(
            f"{provider.authorization_endpoint}?{query}",
            state,
            nonce,
            SecretStr(verifier),
            redirect_uri,
            _utc_now() + timedelta(minutes=5),
            self._resource_audience,
        )

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: SecretText,
        resource_audience: str | None = None,
    ) -> UnverifiedOidcTokenResponse:
        require_code_exchange(
            code=code,
            redirect_uri=redirect_uri,
            verifier=code_verifier,
            resource_audience=resource_audience,
            expected_resource=self._resource_audience,
        )
        provider = await self.discovery()
        started = _utc_now()
        try:
            response = await self._client.post(
                provider.token_endpoint,
                headers={"Accept": "application/json"},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._client_id,
                    "code_verifier": code_verifier.get_secret_value(),
                    **({"resource": resource_audience} if resource_audience else {}),
                },
            )
            response.raise_for_status()
            return _token_response(response, started)
        except (httpx.HTTPError, ValidationError, ValueError, TypeError) as exc:
            raise OidcProviderUnavailable("OIDC token exchange unavailable") from exc

    async def verify_exchanged_id_token(
        self,
        *,
        tokens: UnverifiedOidcTokenResponse,
        expected_nonce: str,
    ) -> VerifiedOidcIdentity:
        metadata = await self.discovery()
        return await verify_rauthy_id_token(
            tokens.id_token,
            expected_nonce=expected_nonce,
            issuer=metadata.issuer,
            client_id=self._client_id,
            jwks_uri=metadata.jwks_uri,
            client=self._client,
        )

    async def verify_current_userinfo(
        self,
        *,
        tokens: UnverifiedOidcTokenResponse,
        identity: VerifiedOidcIdentity,
    ) -> None:
        verified = _checked_identity(identity)
        require_userinfo_identity(
            verified, issuer=self._issuer, client_id=self._client_id, now=_utc_now()
        )
        raw = _checked_bearer(tokens.access_token.get_secret_value())
        metadata = await self.discovery()
        if metadata.userinfo_endpoint is None:
            raise OidcProviderUnavailable("Rauthy Userinfo endpoint unavailable")
        try:
            response = await self._client.get(
                metadata.userinfo_endpoint,
                follow_redirects=False,
                headers={"Authorization": "Bearer " + raw, "Accept": "application/json"},
            )
        except (httpx.HTTPError, ValueError):
            raise OidcProviderUnavailable("Rauthy Userinfo endpoint unavailable") from None
        _require_userinfo_reply(response, identity.subject)

    async def verify_resource(
        self,
        tokens: UnverifiedOidcTokenResponse,
        identity: VerifiedOidcIdentity,
        audience: str,
    ) -> PrivateOidcResourceCredential:
        metadata = await self.discovery()
        return await verify_resource_credential(
            token=tokens.access_token,
            identity=identity,
            resource_audience=audience,
            token_deadline=tokens.deadline,
            jwks_uri=metadata.jwks_uri,
            client=self._client,
        )

    async def capture_refresh(
        self,
        tokens: UnverifiedOidcTokenResponse,
        identity: VerifiedOidcIdentity,
    ) -> VerifiedRefreshCredential | None:
        return await _capture_refresh(self, tokens, identity)

    async def authenticate_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: SecretStr,
        expected_nonce: str,
        expected_issuer: str,
        resource_audience: str | None,
    ) -> VerifiedOidcLogin:
        return await AuthenticateOidcCode(self, _utc_now).execute(
            CompleteOidcCode(
                code,
                redirect_uri,
                code_verifier,
                expected_nonce,
                expected_issuer,
                resource_audience,
            )
        )

    async def public_configuration(self) -> PublicOidcConfiguration:
        metadata = await self.discovery()
        return PublicOidcConfiguration(
            metadata.issuer,
            self._client_id,
            metadata.authorization_endpoint,
            metadata.token_endpoint,
            metadata.jwks_uri,
            metadata.userinfo_endpoint,
        )


def _token_response(response: httpx.Response, started: datetime) -> UnverifiedOidcTokenResponse:
    mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if len(response.content) > 65536 or mime != "application/json":
        raise OidcProviderUnavailable("OIDC token response malformed")
    validate_unique_fields(response.content)
    tokens = UnverifiedOidcTokenResponse.model_validate_json(response.content)
    if tokens.token_type.lower() != "bearer":
        raise OidcProviderUnavailable("OIDC token type unsupported")
    tokens._request_started = started
    return tokens
