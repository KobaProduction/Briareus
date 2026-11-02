"""Private native-login state; provider challenges never establish membership."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol


class SecretText(Protocol):
    """Read capability for protected text, without a provider/framework dependency."""

    def get_secret_value(self) -> str: ...


@dataclass(frozen=True, slots=True)
class NativeCredentials:
    email: SecretText = field(repr=False)
    password: SecretText = field(repr=False)
    pow: SecretText = field(repr=False)


@dataclass(frozen=True, slots=True)
class PrivateNativePending:
    """Claim bound to the original issuer, PKCE nonce and one-use generation."""

    state: str
    issuer: str
    client_id: str
    nonce: str
    verifier: SecretText = field(repr=False)
    csrf: SecretText = field(repr=False)
    provider_cookie: SecretText = field(repr=False)
    expires_at: datetime
    claim_id: SecretText = field(repr=False)
    resource_audience: str | None = None


@dataclass(frozen=True, slots=True)
class PrivateNativeOtpPending:
    original: PrivateNativePending
    attempt_id: SecretText = field(repr=False)
    selected_otp_id: SecretText | None = field(default=None, repr=False)
    login_code: SecretText | None = field(default=None, repr=False)
    finish_code: SecretText | None = field(default=None, repr=False)
    provider_cookie: SecretText | None = field(default=None, repr=False)


NativeStepState = Literal[
    "oauth_callback_pending",
    "otp_pending",
    "webauthn_pending",
    "tos_pending",
    "account_update_required",
    "client_mfa_required",
    "rate_limited",
    "credentials_rejected",
    "request_rejected",
    "provider_access_denied",
]
OtpKind = Literal["email", "phone", "time"]


class NativeProviderProtocolUnavailable(Exception):
    """An unsupported provider result cannot establish a signed user session."""


@dataclass(frozen=True, slots=True)
class PrivateNativeLoginStep:
    state: NativeStepState
    secret: SecretText | None = field(default=None, repr=False)
    challenge_kinds: tuple[OtpKind, ...] = ()
    private_otp_ids: tuple[SecretText, ...] = field(default=(), repr=False)
    provider_cookie: SecretText | None = field(default=None, repr=False)
    csrf_token: SecretText | None = field(default=None, repr=False)
    retry_not_before: int | None = None
    expires_at: int | None = None
    private_denial_class: (
        Literal["csrf", "session_expired", "ambiguous_unauthorized", "other_auth", "unclassified"]
        | None
    ) = None

    @property
    def requires_restart(self) -> bool:
        return self.state in {
            "webauthn_pending",
            "tos_pending",
            "account_update_required",
            "client_mfa_required",
        }

    def available_otp_methods(self) -> tuple[tuple[OtpKind, SecretText], ...]:
        """Pinned provider implements email only; never advertise Time or Phone."""
        if len(self.challenge_kinds) != len(self.private_otp_ids):
            raise NativeProviderProtocolUnavailable("private OTP methods are ambiguous")
        return tuple(
            (kind, otp_uuid)
            for kind, otp_uuid in zip(self.challenge_kinds, self.private_otp_ids, strict=True)
            if kind == "email"
        )


@dataclass(frozen=True, slots=True)
class NativeLoginResult:
    """Public outcome plus an optional server cookie, never provider credentials."""

    status: int
    stage: str = ""
    error_code: str | None = None
    continuation_available: bool = False
    restart_required: bool = False
    methods: tuple[OtpKind, ...] = ()
    retry_not_before: int | None = None
    expires_at: int | None = None
    ticket: str | None = field(default=None, repr=False)
    session_seconds: int = 0
    expires_in: int | None = None
    challenge: str | None = None

    @property
    def preserves_claim(self) -> bool:
        return self.status in {200, 202}


def login_failure(status: int, code: str) -> NativeLoginResult:
    return NativeLoginResult(status=status, error_code=code)
