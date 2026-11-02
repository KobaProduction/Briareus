#!/usr/bin/env python3
"""Exercise ONE anonymous native Init -> PoW -> Cancel on the pinned public Dev.

Unlike probe_dev_native_auth.py's read-only GET checks, this explicit command
allocates and retires a short-lived anonymous Rauthy provider transaction via
the Briareus API. No account, password, OTP, token or Cedar grant is requested.
Never log the response bodies, provider challenge or transaction cookie.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from http.client import HTTPException
from http.cookiejar import CookieJar
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

ORIGIN = "https://briareus.koba-nexus.ru"
HOST = "briareus.koba-nexus.ru"
COOKIE = "__Host-briareus_native_transaction"
PATHS = frozenset(
    {
        "/api/v1/auth/start",
        "/api/v1/auth/pow",
        "/api/v1/auth/cancel",
    }
)
MAX_BODY = 8192
TIMEOUT = 12


class _AnonymousDocument(Enum):
    START = "start"
    POW = "pow"
    OTHER_OBJECT = "other_object"


@dataclass(slots=True)
class _AnonymousFields:
    first_factor_stage: bool = False
    unauthenticated: bool = False
    bounded_expiry: bool = False
    printable_challenge: bool = False

    def classify(self, keys: set[str]) -> _AnonymousDocument:
        if (
            keys == {"stage", "authenticated", "expires_in"}
            and self.first_factor_stage
            and self.unauthenticated
            and self.bounded_expiry
        ):
            return _AnonymousDocument.START
        if (
            keys == {"challenge", "authenticated"}
            and self.unauthenticated
            and self.printable_challenge
        ):
            return _AnonymousDocument.POW
        return _AnonymousDocument.OTHER_OBJECT


@dataclass(slots=True)
class ProbeReport:
    scope: str = "exact Dev origin, single anonymous Init/PoW/Cancel, no credentials"
    start_status: int = 0
    start_valid: bool = False
    pending_cookie_scoped: bool = False
    pow_status: int = 0
    pow_valid: bool = False
    cancel_status: int = 0
    anonymous_transaction_retired: bool = False
    user_password_or_otp_submitted: bool = False
    signed_user_project_or_cedar_verified: bool = False
    passed: bool = False


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    document: _AnonymousDocument | None
    media_type: str
    no_store: bool
    no_cache: bool
    redirected: bool


class ProbeTransport(Protocol):
    def post(self, path: str) -> Reply: ...

    def pending(self) -> bool: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _unique_keys(keys: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            raise ValueError("ambiguous JSON")
        seen.add(key)
    return seen


def _printable_challenge(challenge: str) -> bool:
    return (
        2 <= len(challenge) <= 128
        and challenge.isascii()
        and all(33 <= ord(char) <= 126 for char in challenge)
    )


def _unique_pairs(pairs: list[tuple[str, object]]) -> _AnonymousDocument:
    # json.loads invokes this for every nested object before its parent.
    # Reject all duplicate keys before classifying either anonymous contract.
    keys = _unique_keys(key for key, _ in pairs)
    fields = _AnonymousFields()
    for key, value in pairs:
        if key == "stage":
            fields.first_factor_stage = value == "first_factor_required"
        elif key == "authenticated":
            fields.unauthenticated = value is False
        elif key == "expires_in":
            fields.bounded_expiry = type(value) is int and 1 <= value <= 300
        elif key == "challenge":
            fields.printable_challenge = isinstance(value, str) and _printable_challenge(value)
    return fields.classify(keys)


class NativeAnonymousTransport:
    """Isolated memory-only cookie jar; no filesystem or shared browser."""

    def __init__(self) -> None:
        self._cookies = CookieJar()
        self._opener = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(self._cookies), NoRedirect()
        )

    def pending(self) -> bool:
        cookies = list(self._cookies)
        if len(cookies) != 1:
            return False
        cookie = cookies[0]
        return (
            cookie.name == COOKIE
            and cookie.domain == HOST
            and not cookie.domain_specified
            and cookie.path == "/"
            and cookie.secure
            and not cookie.is_expired()
            and cookie.value is not None
            and 16 <= len(cookie.value) <= 256
        )

    def post(self, path: str) -> Reply:
        if path not in PATHS:
            raise ValueError("only pinned anonymous native paths permitted")
        request = Request(
            ORIGIN + path,
            data=b"{}",
            headers={
                "Host": HOST,
                "Origin": ORIGIN,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Length": "2",
                "User-Agent": "Briareus-Dev-Anon-Prelogin/1",
            },
            method="POST",
        )
        try:
            reply = self._opener.open(request, timeout=TIMEOUT)
        except HTTPError as error:
            reply = error
        with reply:
            content = reply.read(MAX_BODY + 1)
            if len(content) > MAX_BODY:
                raise ValueError("provider reply exceeded bound")
            document: _AnonymousDocument | None = None
            if content:
                try:
                    parsed = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_pairs)
                    if isinstance(parsed, _AnonymousDocument):
                        document = parsed
                except (ValueError, UnicodeError, RecursionError):
                    pass
            return Reply(
                status=reply.status,
                document=document,
                media_type=reply.headers.get_content_type(),
                no_store=reply.headers.get("cache-control") == "no-store",
                no_cache=reply.headers.get("pragma") == "no-cache",
                redirected=reply.status in range(300, 400) or bool(reply.headers.get("location")),
            )


def _safe_status(reply: Reply) -> bool:
    return (
        reply.media_type == "application/json"
        and reply.no_store
        and reply.no_cache
        and not reply.redirected
    )


def _start_valid(reply: Reply) -> bool:
    return (
        reply.status == 201 and _safe_status(reply) and reply.document is _AnonymousDocument.START
    )


def _pow_valid(reply: Reply) -> bool:
    return reply.status == 200 and _safe_status(reply) and reply.document is _AnonymousDocument.POW


def inspect(transport: ProbeTransport | None = None) -> ProbeReport:
    client = NativeAnonymousTransport() if transport is None else transport
    result = ProbeReport()
    try:
        start = client.post("/api/v1/auth/start")
        result.start_status = start.status
        result.start_valid = _start_valid(start)
        result.pending_cookie_scoped = client.pending()
        if result.start_valid and result.pending_cookie_scoped:
            proof = client.post("/api/v1/auth/pow")
            result.pow_status = proof.status
            result.pow_valid = _pow_valid(proof)
    except (OSError, HTTPException, URLError, ValueError, TimeoutError, TypeError):
        # Never reflect upstream cookie/challenge/provider exception details.
        pass
    finally:
        try:
            if client.pending():
                canceled = client.post("/api/v1/auth/cancel")
                result.cancel_status = canceled.status
                result.anonymous_transaction_retired = (
                    canceled.status == 204
                    and canceled.document is None
                    and canceled.no_store
                    and canceled.no_cache
                    and not canceled.redirected
                    and not client.pending()
                )
        except (OSError, HTTPException, URLError, ValueError, TimeoutError, TypeError):
            pass
    result.passed = all(
        value is True
        for value in (
            result.start_valid,
            result.pending_cookie_scoped,
            result.pow_valid,
            result.anonymous_transaction_retired,
        )
    )
    return result


def main() -> int:
    report = inspect()
    signed_authority_verified = report.signed_user_project_or_cedar_verified
    print(
        json.dumps(
            {
                "scope": report.scope,
                "start_status": report.start_status,
                "start_valid": report.start_valid,
                "pending_cookie_scoped": report.pending_cookie_scoped,
                "pow_status": report.pow_status,
                "pow_valid": report.pow_valid,
                "cancel_status": report.cancel_status,
                "anonymous_transaction_retired": report.anonymous_transaction_retired,
                "user_password_or_otp_submitted": report.user_password_or_otp_submitted,
                "signed_user_project_or_cedar_verified": signed_authority_verified,
                "pass": report.passed,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
