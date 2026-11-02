"""Pinned-key PyJWT adapter and strict provider wire decoding."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from pydantic import ValidationError

from authorization.domain.rauthy import (
    RauthyKeysUnavailable,
    RauthyTokenRejected,
    ResourceTokenAudience,
    ResourceTokenClaims,
    SigningKeyMetadata,
    TrustedIssuer,
    VerifiedRauthySubject,
)
from runtime_peer.oidc_wire import (
    BearerBindings,
    EdwardsSigningKey,
    IssuerSigningHeader,
    IssuerSigningKey,
    IssuerSigningKeys,
)


class _Claims(BearerBindings):
    sub: str
    exp: int
    iat: int
    nbf: int
    typ: str
    azp: str
    jti: str
    aud: str | list[str]

    def domain(self) -> ResourceTokenClaims:
        audiences = (self.aud,) if isinstance(self.aud, str) else tuple(self.aud)
        return ResourceTokenClaims(
            self.sub,
            self.exp,
            self.iat,
            self.nbf,
            self.typ,
            self.confirmation_bound,
            self.azp,
            self.jti,
            audiences,
        )


def signing_metadata(key: IssuerSigningKey) -> SigningKeyMetadata:
    return SigningKeyMetadata(
        key.kid,
        key.alg,
        key.kty,
        isinstance(key, EdwardsSigningKey) and key.crv == "Ed25519",
        key.use == "sig",
        key.key_ops in (None, ["verify"]),
        frozenset(key.model_fields_set),
    )


@dataclass(frozen=True, slots=True)
class TrustedSigningKey:
    identifier: str
    key: jwt.PyJWK


@dataclass(frozen=True, slots=True)
class TrustedSigningKeys:
    entries: tuple[TrustedSigningKey, ...]

    def get(self, identifier: str) -> jwt.PyJWK | None:
        return next((entry.key for entry in self.entries if entry.identifier == identifier), None)


def _trusted_keys(document: IssuerSigningKeys) -> TrustedSigningKeys:
    try:
        entries = document.keys
        if not 1 <= len(entries) <= 16:
            raise RauthyKeysUnavailable("Rauthy trusted JWKS key set missing or oversized")
        keys: list[TrustedSigningKey] = []
        identifiers: set[str] = set()
        for metadata in entries:
            signing_metadata(metadata).validate()
            if metadata.kid in identifiers:
                raise RauthyKeysUnavailable("Rauthy trusted JWK metadata rejected")
            key = jwt.PyJWK.from_dict(
                metadata.model_dump(exclude_unset=True), algorithm=metadata.alg
            )
            keys.append(TrustedSigningKey(metadata.kid, key))
            identifiers.add(metadata.kid)
        return TrustedSigningKeys(tuple(keys))
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise RauthyKeysUnavailable("Rauthy trusted signing key rejected") from exc


class RauthyJwksVerifier:
    """Verify expected resource-audience tokens using independently trusted keys."""

    def __init__(
        self,
        *,
        issuer: str,
        resource_audience: str,
        oauth_client_id: str,
        trusted_jwks: IssuerSigningKeys,
    ) -> None:
        self._issuer = TrustedIssuer(issuer).issuer
        self._audience = ResourceTokenAudience(resource_audience, oauth_client_id).resource
        self._keys = _trusted_keys(trusted_jwks)

    def _signer(self, token: str) -> jwt.PyJWK:
        raw = jwt.get_unverified_header(token)
        header = IssuerSigningHeader.model_validate(raw)
        signer = self._keys.get(header.kid)
        if signer is None or header.alg != signer.algorithm_name or header.critical:
            raise RauthyTokenRejected("Rauthy token signer not trusted")
        return signer

    def verify_access_token(self, token: object) -> VerifiedRauthySubject:
        if not isinstance(token, str) or not 40 <= len(token) <= 8192:
            raise RauthyTokenRejected("Rauthy bearer invalid")
        try:
            signer = self._signer(token)
            claims = _Claims.model_validate(
                jwt.decode(
                    token,
                    key=signer.key,
                    algorithms=[signer.algorithm_name],
                    issuer=self._issuer,
                    audience=self._audience,
                    leeway=0,
                    options={
                        "require": ["iss", "aud", "sub", "exp", "iat", "nbf", "typ", "azp", "jti"]
                    },
                )
            )
            return claims.domain().verify(self._issuer, self._audience)
        except (jwt.PyJWTError, TypeError, ValueError, OverflowError, ValidationError) as exc:
            raise RauthyTokenRejected("Rauthy bearer rejected") from exc
