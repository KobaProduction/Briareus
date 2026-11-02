"""Fixed browser write-stage records; stronger validation stays at existing reads."""

import json
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True, slots=True, repr=False)
class OidcTransactionWrite:
    nonce: str
    verifier: str
    issuer: str
    client_id: str
    resource_audience: str | None
    expires_at: str


@dataclass(frozen=True, slots=True, repr=False)
class NativeInitWrite:
    stage: Literal["init"]
    deadline_ms: int
    state: str
    expires_at: str
    resource_audience: str | None
    nonce: str
    verifier: str
    issuer: str
    client_id: str
    csrf: str
    provider_cookie: str


@dataclass(frozen=True, slots=True, repr=False)
class NativeOtpMethodWrite:
    kind: str
    id: str


@dataclass(frozen=True, slots=True, repr=False)
class NativeOtpWrite:
    stage: Literal["otp_ready"]
    claim: str
    deadline_ms: int
    state: str
    issuer: str
    client_id: str
    nonce: str
    verifier: str
    csrf: str
    provider_cookie: str
    resource_audience: str | None
    otp_login_code: str
    methods: tuple[NativeOtpMethodWrite, ...]


def encode_browser_write(record: OidcTransactionWrite | NativeInitWrite | NativeOtpWrite) -> str:
    return json.dumps(asdict(record), separators=(",", ":"))
