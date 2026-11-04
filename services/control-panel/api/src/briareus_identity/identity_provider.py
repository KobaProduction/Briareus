"""Shared ZITADEL wire adapter; application sessions remain service-owned."""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from briareus_identity.identity_settings import ZitadelSettings


class IdentityProviderError(RuntimeError):
    """Provider evidence is missing, invalid, or unavailable."""


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    jwks_uri: str
    introspection_endpoint: str
    revocation_endpoint: str
    end_session_endpoint: str = ""


class ProviderIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, validate_by_name=True)
    sub: str = Field(min_length=1)
    iss: str = ""
    preferred_username: str = Field(
        "", validation_alias=AliasChoices("preferred_username", "username")
    )
    email: str = ""
    exp: int = 0
    scope: str = ""
    client_id: str = ""
    aud: str | list[str] = ""
    active: bool = False

    @property
    def display_name(self) -> str:
        return self.preferred_username or self.email or self.sub


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    access_token: str = Field(min_length=1, repr=False)
    id_token: str = Field("", repr=False)
    refresh_token: str = Field("", repr=False)
    expires_in: int = Field(gt=0)
    token_type: str
    scope: str = ""


@dataclass(frozen=True)
class VerifiedLogin:
    identity: ProviderIdentity
    expires_at: int
    access_token: str = field(repr=False)
    id_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


class ZitadelClient:
    def __init__(self, settings: ZitadelSettings) -> None:
        settings.validate_bootstrap()
        self.settings = settings
        self._metadata: ProviderMetadata | None = None
        self._keys: jwt.PyJWKClient | None = None

    def metadata(self) -> ProviderMetadata:
        if self._metadata is None:
            try:
                with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                    response = client.get(self.settings.discovery_url)
                    response.raise_for_status()
                metadata = ProviderMetadata.model_validate(response.json())
                self._validate_metadata(metadata)
                self._metadata = metadata
            except (httpx.HTTPError, ValueError) as error:
                raise IdentityProviderError(
                    "ZITADEL discovery is unavailable or invalid"
                ) from error
        return self._metadata

    def _validate_metadata(self, metadata: ProviderMetadata) -> None:
        if metadata.issuer != self.settings.canonical_issuer:
            raise IdentityProviderError("ZITADEL discovery issuer does not match configuration")
        origin = urlsplit(metadata.issuer)
        for endpoint in (
            metadata.authorization_endpoint,
            metadata.token_endpoint,
            metadata.userinfo_endpoint,
            metadata.jwks_uri,
            metadata.introspection_endpoint,
            metadata.revocation_endpoint,
            metadata.end_session_endpoint,
        ):
            if not endpoint:
                continue
            parsed = urlsplit(endpoint)
            if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                raise IdentityProviderError("ZITADEL discovery contains an untrusted endpoint")

    def authorization_url(
        self, *, callback_url: str, state: str, nonce: str, challenge: str
    ) -> str:
        query = urlencode(
            {
                "client_id": self.settings.client_id,
                "response_type": "code",
                "redirect_uri": callback_url,
                "scope": "openid profile email offline_access",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return self.metadata().authorization_endpoint + "?" + query

    def exchange_code(
        self, *, code: str, callback_url: str, verifier: str, nonce: str
    ) -> VerifiedLogin:
        try:
            with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                response = client.post(
                    self.metadata().token_endpoint,
                    auth=(self.settings.client_id, self.settings.resolved_client_secret),
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": callback_url,
                        "code_verifier": verifier,
                    },
                )
                response.raise_for_status()
            tokens = TokenResponse.model_validate(response.json())
            if tokens.token_type.casefold() != "bearer":
                raise IdentityProviderError("ZITADEL returned an unsupported token type")
            identity = self._verify_id_token(tokens.id_token, nonce)
            return VerifiedLogin(
                identity,
                min(identity.exp, int(time.time()) + tokens.expires_in),
                tokens.access_token,
                tokens.id_token,
                tokens.refresh_token,
            )
        except (httpx.HTTPError, ValueError, jwt.PyJWTError) as error:
            raise IdentityProviderError("ZITADEL authorization could not be verified") from error

    def _verify_id_token(self, token: str, nonce: str) -> ProviderIdentity:
        if not token:
            raise IdentityProviderError("ZITADEL did not issue an identity token")
        if self._keys is None:
            self._keys = jwt.PyJWKClient(
                self.metadata().jwks_uri,
                timeout=self.settings.request_timeout_seconds,
            )
        key = self._keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=self.settings.client_id,
            issuer=self.settings.canonical_issuer,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
        )
        received_nonce = claims.get("nonce")
        if not isinstance(received_nonce, str) or not hmac.compare_digest(received_nonce, nonce):
            raise IdentityProviderError("ZITADEL identity nonce is invalid")
        return self.require_allowed_identity(ProviderIdentity.model_validate(claims))

    def require_allowed_identity(self, identity: ProviderIdentity) -> ProviderIdentity:
        if identity.iss != self.settings.canonical_issuer:
            raise IdentityProviderError("ZITADEL identity issuer is invalid")
        if identity.sub not in self.settings.allowed_subjects:
            raise IdentityProviderError("ZITADEL subject has no Briareus access")
        return identity

    def introspect(self, token: str) -> ProviderIdentity:
        try:
            with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                response = client.post(
                    self.metadata().introspection_endpoint,
                    auth=(self.settings.client_id, self.settings.resolved_client_secret),
                    data={"token": token},
                )
                response.raise_for_status()
            identity = ProviderIdentity.model_validate(response.json())
            if not identity.active or identity.exp <= time.time():
                raise IdentityProviderError("ZITADEL access token is inactive")
            audiences = [identity.aud] if isinstance(identity.aud, str) else identity.aud
            if self.settings.client_id not in audiences or not identity.client_id:
                raise IdentityProviderError("ZITADEL access token audience is invalid")
            return self.require_allowed_identity(identity)
        except (httpx.HTTPError, ValueError) as error:
            raise IdentityProviderError("ZITADEL access token could not be verified") from error

    def revoke(self, token: str) -> None:
        if not token:
            return
        try:
            with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
                response = client.post(
                    self.metadata().revocation_endpoint,
                    auth=(self.settings.client_id, self.settings.resolved_client_secret),
                    data={"token": token},
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise IdentityProviderError("ZITADEL token revocation is unavailable") from error

    def logout_url(self, *, id_token: str, return_url: str) -> str:
        endpoint = self.metadata().end_session_endpoint
        if not endpoint:
            return return_url
        return (
            endpoint
            + "?"
            + urlencode(
                {
                    "id_token_hint": id_token,
                    "post_logout_redirect_uri": return_url,
                }
            )
        )
