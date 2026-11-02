"""Provider identity invariants, independent of JWT and HTTP implementations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit


class RauthyTokenRejected(Exception):
    """Untrusted, invalid, incorrectly scoped, or expired provider token."""


class RauthyKeysUnavailable(Exception):
    """No currently trusted provider signing keys were supplied."""


@dataclass(frozen=True, slots=True)
class VerifiedRauthySubject:
    subject: str
    issuer: str
    audience: str
    expires_at: datetime


_USER_SUBJECT = re.compile(r"[A-Za-z0-9]{24}\Z", re.ASCII)
ALLOWED_ALGORITHMS = frozenset({"EdDSA", "RS256", "RS384", "RS512"})
FORBIDDEN_JWK_FIELDS = frozenset(
    {"jku", "x5u", "x5c", "x5t", "d", "p", "q", "dp", "dq", "qi", "oth"}
)
FORBIDDEN_HEADER_FIELDS = frozenset({"jku", "jwk", "x5u", "x5c"})


@dataclass(frozen=True, slots=True)
class TrustedIssuer:
    issuer: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.issuer)
        valid_origin = parsed.scheme == "https" and bool(parsed.hostname)
        credentials = parsed.username is not None or parsed.password is not None
        if (
            not valid_origin
            or credentials
            or parsed.query
            or parsed.fragment
            or not self.issuer.endswith("/")
        ):
            raise ValueError("exact trusted HTTPS issuer required")

    def signing_keys_uri(self, metadata_issuer: str, uri: str) -> str:
        if metadata_issuer != self.issuer:
            raise RauthyKeysUnavailable("Rauthy metadata issuer mismatch")
        expected, actual = urlsplit(self.issuer), urlsplit(uri)
        same_origin = actual.scheme == "https" and actual.netloc == expected.netloc
        credentials = actual.username is not None or actual.password is not None
        child_path = actual.path.startswith(expected.path) and actual.path != expected.path
        if not same_origin or credentials or actual.query or actual.fragment or not child_path:
            raise RauthyKeysUnavailable("Rauthy signing-key URI outside trusted issuer")
        return uri


@dataclass(frozen=True, slots=True)
class ResourceTokenAudience:
    resource: str
    oauth_client: str

    def __post_init__(self) -> None:
        if not self.resource or not self.oauth_client or self.resource == self.oauth_client:
            raise ValueError("Rauthy issuer and distinct resource audience required")


@dataclass(frozen=True, slots=True)
class SigningKeyMetadata:
    identifier: str
    algorithm: str
    key_type: str
    ed25519_curve: bool
    signing_usage: bool
    verification_only: bool
    fields: frozenset[str]

    def validate(self) -> None:
        if not 1 <= len(self.identifier) <= 128 or self.algorithm not in ALLOWED_ALGORITHMS:
            raise RauthyKeysUnavailable("Rauthy trusted JWK metadata rejected")
        expected_type = "OKP" if self.algorithm == "EdDSA" else "RSA"
        if self.key_type != expected_type or (self.algorithm == "EdDSA" and not self.ed25519_curve):
            raise RauthyKeysUnavailable("Rauthy trusted JWK metadata rejected")
        if not self.signing_usage or not self.verification_only:
            raise RauthyKeysUnavailable("Rauthy trusted JWK metadata rejected")
        if self.fields & FORBIDDEN_JWK_FIELDS:
            raise RauthyKeysUnavailable("Rauthy trusted JWK metadata rejected")


@dataclass(frozen=True, slots=True)
class ResourceTokenClaims:
    subject: str
    expires: int
    issued: int
    not_before: int
    bearer_kind: str
    proof_bound: bool
    authorized_party: str
    token_id: str
    audiences: tuple[str, ...]

    def verify(self, issuer: str, audience: str) -> VerifiedRauthySubject:
        self._identity_and_times()
        self._client_and_token()
        if not 1 <= len(self.audiences) <= 16 or any(not item for item in self.audiences):
            raise RauthyTokenRejected("Rauthy signed subject invalid")
        if len(set(self.audiences)) != len(self.audiences):
            raise RauthyTokenRejected("Rauthy signed subject invalid")
        return VerifiedRauthySubject(
            self.subject, issuer, audience, datetime.fromtimestamp(self.expires, tz=UTC)
        )

    def _identity_and_times(self) -> None:
        if _USER_SUBJECT.fullmatch(self.subject) is None:
            raise RauthyTokenRejected("Rauthy signed subject invalid")
        if self.expires <= self.issued or self.not_before >= self.expires:
            raise RauthyTokenRejected("Rauthy signed subject invalid")
        if self.bearer_kind != "Bearer" or self.proof_bound:
            raise RauthyTokenRejected("Rauthy signed subject invalid")

    def _client_and_token(self) -> None:
        client, identifier = self.authorized_party, self.token_id
        if (
            not 1 <= len(client) <= 2048
            or not client.isascii()
            or any(char.isspace() for char in client)
        ):
            raise RauthyTokenRejected("Rauthy signed subject invalid")
        if not 1 <= len(identifier) <= 128 or not identifier.isascii():
            raise RauthyTokenRejected("Rauthy signed subject invalid")
        if any(ord(char) <= 32 or ord(char) >= 127 for char in identifier):
            raise RauthyTokenRejected("Rauthy signed subject invalid")
