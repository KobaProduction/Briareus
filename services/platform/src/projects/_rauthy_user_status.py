"""Pinned Rauthy v0.37.1 private Users:read status; no IAM claims as grants.

Upstream contract reviewed at sebadob/rauthy tag v0.37.1, git ce35a70f:
- src/api/src/users.rs GET /users/{id} validates Users:read API-Key.
- src/api_types/src/users.rs UserResponse: id, enabled, user_expires.
- src/service/src/token_set.rs ID-token sub is user.id.
- src/common/src/utils.rs new_store_id() is 24 alphanumeric characters.

A read-only scoped key is supplied ONLY by the trusted Platform process.
Never derive a Rauthy Admin credential or URL from a browser session.
"""

from __future__ import annotations

import asyncio
import os
import ssl
import stat
from datetime import UTC, datetime
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler

from pydantic import SecretStr

from common.platform_db import PlatformDatabase
from projects._oidc_membership_projection import PlatformOidcMembershipProjection
from projects._rauthy_user_links import (
    PlatformCurrentSubjectLinkReader,
    VerifiedRauthyUserStatus,
)
from projects.domain.user_links import RAUTHY_SUBJECT_PATTERN
from projects.domain.user_links import canonical_subject as canonical_subject
from projects.infrastructure.rauthy_protocol import PrivateUserResponse as PrivateUserResponse
from projects.infrastructure.rauthy_protocol import (
    RauthyUserStatusUnavailable as RauthyUserStatusUnavailable,
)
from projects.infrastructure.rauthy_protocol import decode_user_status

_PUBLIC_ISSUER = (
    "https://127.0.0.1/auth/v1/"
    if os.environ.get("BRIAREUS_LOCAL_TESTING") == "1"
    else "https://briareus.koba-nexus.ru/auth/v1/"
)
_LOCAL_SANDBOX_ISSUER = "https://localhost:18444/auth/v1/"
_USERS_BY_ID = "/auth/v1/users/"
_MAX_JSON = 65_536
_ID = RAUTHY_SUBJECT_PATTERN


def email_selector(value: object) -> bool:
    return (
        isinstance(value, str)
        and 3 <= len(value) <= 254
        and "@" in value
        and not any(ord(char) < 33 for char in value)
    )


def local_certificate(value: object) -> bool:
    return (
        isinstance(value, str)
        and 256 <= len(value) <= 8192
        and "-----BEGIN CERTIFICATE-----" in value
        and "-----BEGIN PRIVATE KEY-----" not in value
    )


class RauthyUserPrivateTransport(Protocol):
    async def read_user(self, *, subject: str) -> PrivateUserResponse:
        """Fixed, private, authenticated read only. Must never redirect."""
        ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        raise RauthyUserStatusUnavailable("Rauthy private Users API redirected")


class FixedRauthyUsersTransport:
    """Only the exact private DNS host; no system proxy, redirect or user URL."""

    def __init__(
        self,
        *,
        users_read_api_key: SecretStr,
        test_only_local_ca_pem: str | None = None,
    ) -> None:
        if not isinstance(users_read_api_key, SecretStr):
            raise ValueError("private scoped Rauthy Users:read key required")
        key = users_read_api_key.get_secret_value()
        if (
            not 1 <= len(key) <= 4096
            or not key.isascii()
            or any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in key)
        ):
            raise ValueError("private Rauthy User read key syntax unsafe")
        self._key = users_read_api_key
        self._tls_context: ssl.SSLContext | None = None
        if test_only_local_ca_pem is None:
            return
        # No trust_env, certificate bypass or caller-controlled host.
        # This is ONLY the independent disposable localhost Rauthy.
        if not local_certificate(test_only_local_ca_pem):
            raise ValueError("local Rauthy TLS certificate required")
        try:
            self._tls_context = ssl.create_default_context(cadata=test_only_local_ca_pem)
        except (ssl.SSLError, ValueError):
            raise ValueError("untrusted disposable Rauthy certificate") from None

    def _read_sync(self, subject: str, *, by_email: bool = False) -> PrivateUserResponse:
        # No arbitrary URL or request-supplied host is ever contacted.
        target = (_USERS_BY_ID + "email/" if by_email else _USERS_BY_ID) + quote(subject, safe="")
        connection = (
            HTTPSConnection("localhost", 18444, context=self._tls_context, timeout=3)
            if self._tls_context is not None
            else HTTPConnection("briareus-rauthy", 8080, timeout=3)
        )
        try:
            connection.request(
                "GET",
                target,
                headers={
                    "Authorization": "API-Key " + self._key.get_secret_value(),
                    "Accept": "application/json",
                },
            )
            with connection.getresponse() as response:
                if response.status != 200:
                    return PrivateUserResponse(response.status, "", b"")
                if response.headers.get_content_type() != "application/json":
                    raise RauthyUserStatusUnavailable("private Rauthy Users response not JSON")
                body = response.read(_MAX_JSON + 1)
                if len(body) > _MAX_JSON:
                    raise RauthyUserStatusUnavailable("Rauthy Users response over maximum")
                return PrivateUserResponse(200, "application/json", body)
        except (OSError, HTTPException, ValueError) as exc:
            raise RauthyUserStatusUnavailable("private Rauthy Users API unavailable") from exc
        finally:
            connection.close()

    async def read_user(self, *, subject: str) -> PrivateUserResponse:
        if not canonical_subject(subject):
            raise RauthyUserStatusUnavailable("noncanonical Rauthy subject")
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._read_sync, subject), timeout=3.5)
        except TimeoutError:
            raise RauthyUserStatusUnavailable("Rauthy Users API timed out") from None

    async def read_by_email(self, *, email: str) -> PrivateUserResponse:
        # Pinned Rauthy GET /users/email/{email}; same Users:read authority.
        if not email_selector(email):
            raise RauthyUserStatusUnavailable("Invalid provider email selector")
        return await asyncio.wait_for(
            asyncio.to_thread(self._read_sync, email, by_email=True), timeout=3.5
        )


class FileRauthyUsersTransport:
    """Read an owner-provisioned key lazily, never from request data or ENV."""

    def __init__(self, key_file: str) -> None:
        if key_file != "/var/lib/briareus-platform/rauthy-users-read.key":
            raise ValueError("Exact Platform-owned provider key file required")
        self.path = Path(key_file)

    def _key(self) -> SecretStr:
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or info.st_mode & 0o077:
            raise RauthyUserStatusUnavailable("Platform provider key is not privately provisioned")
        if not 1 <= info.st_size <= 4096:
            raise RauthyUserStatusUnavailable("Platform provider key size invalid")
        return SecretStr(self.path.read_text().strip())

    async def read_user(self, *, subject: str) -> PrivateUserResponse:
        key = await asyncio.to_thread(self._key)
        return await FixedRauthyUsersTransport(users_read_api_key=key).read_user(subject=subject)

    async def read_by_email(self, *, email: str) -> PrivateUserResponse:
        reader = FixedRauthyUsersTransport(users_read_api_key=await asyncio.to_thread(self._key))
        return await reader.read_by_email(email=email)


class CurrentRauthyUserStatusReader:
    """Return only exact enabled/current status; discard all provider PII."""

    def __init__(
        self,
        *,
        private_transport: RauthyUserPrivateTransport,
        test_only_local_issuer: bool = False,
    ) -> None:
        if private_transport is None:
            raise ValueError("trusted Rauthy private Users transport required")
        if type(test_only_local_issuer) is not bool:
            raise ValueError("local provider selector must be an explicit bool")
        self._transport = private_transport
        self._issuer = _LOCAL_SANDBOX_ISSUER if test_only_local_issuer else _PUBLIC_ISSUER

    async def current_status(self, *, issuer: str, subject: str) -> VerifiedRauthyUserStatus:
        # Issuer pin is supplied by the verified Rauthy session or signed
        # service owner, NOT taken from a client JWT URL/Host.
        if issuer != self._issuer or not canonical_subject(subject):
            raise RauthyUserStatusUnavailable("Rauthy issuer or subject not approved")
        try:
            result = await self._transport.read_user(subject=subject)
        except Exception:
            raise RauthyUserStatusUnavailable("private Users:read status unavailable") from None
        return decode_user_status(result, issuer, subject, datetime.now(UTC))


def rauthy_users_transport(
    *,
    users_read_api_key: SecretStr | None = None,
    users_read_key_file: str | None = None,
    test_only_local_ca_pem: str | None = None,
) -> FileRauthyUsersTransport | FixedRauthyUsersTransport:
    """Select exactly one protected provider key source without accessing it."""
    if (users_read_api_key is None) == (users_read_key_file is None):
        raise ValueError("Exactly one owner-provisioned provider key source required")
    private_transport: FileRauthyUsersTransport | FixedRauthyUsersTransport
    if users_read_key_file is not None:
        private_transport = FileRauthyUsersTransport(users_read_key_file)
    else:
        if users_read_api_key is None:
            raise ValueError("Private Rauthy Users:read key required")
        private_transport = FixedRauthyUsersTransport(
            users_read_api_key=users_read_api_key,
            test_only_local_ca_pem=test_only_local_ca_pem,
        )
    return private_transport


def platform_user_membership_with_rauthy(
    *,
    database: PlatformDatabase,
    users_read_api_key: SecretStr | None = None,
    users_read_key_file: str | None = None,
    test_only_local_ca_pem: str | None = None,
) -> PlatformOidcMembershipProjection:
    """Construct request-scoped provider verification and login provisioning."""
    private_transport = rauthy_users_transport(
        users_read_api_key=users_read_api_key,
        users_read_key_file=users_read_key_file,
        test_only_local_ca_pem=test_only_local_ca_pem,
    )
    status_reader = CurrentRauthyUserStatusReader(
        private_transport=private_transport,
        test_only_local_issuer=test_only_local_ca_pem is not None,
    )
    links = PlatformCurrentSubjectLinkReader(
        database=database,
        rauthy_status=status_reader,
    )
    return PlatformOidcMembershipProjection(database=database, subject_links=links)
