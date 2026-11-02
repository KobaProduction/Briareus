"""Pinned Rauthy account creation; provider alone owns setup codes and email."""

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Protocol
from urllib.request import ProxyHandler, Request, build_opener

from projects._rauthy_user_status import _ID, PrivateUserResponse, _NoRedirect
from projects.domain.invitations import InvitationEmail, ProviderUser

_KEY_FILE = Path("/var/lib/briareus-platform/rauthy-users-invite.key")


class InvitationLookupTransport(Protocol):
    async def read_by_email(self, *, email: str) -> PrivateUserResponse: ...


def provisioning_error() -> str | None:
    if os.environ.get("RAUTHY_INVITATION_EMAIL_READY") != "1":
        return "RAUTHY_INVITATION_MAIL_UNCONFIGURED"
    try:
        info = _KEY_FILE.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 1000
            or info.st_mode & 0o077
            or not 1 <= info.st_size <= 4096
        ):
            return "RAUTHY_INVITATION_KEY_UNAVAILABLE"
    except OSError:
        return "RAUTHY_INVITATION_KEY_UNAVAILABLE"
    return None


def create_provider_user(email: str) -> ProviderUser:
    if provisioning_error():
        raise ValueError("Invitation provisioning unavailable")
    key = _KEY_FILE.read_text().strip()
    if not key or not key.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise ValueError("Provider key invalid")
    request = Request(
        "http://briareus-rauthy:8080/auth/v1/users",
        method="POST",
        headers={
            "Authorization": "API-Key " + key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        data=json.dumps(
            {
                "email": email,
                "language": "ru",
                "roles": [],
                "groups": None,
                "given_name": None,
                "family_name": None,
                "user_expires": None,
            }
        ).encode(),
    )
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=3) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("Provider response invalid")
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Provider response too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Provider subject invalid")
        subject, returned_email = result.get("id"), result.get("email")
        if not isinstance(subject, str) or not _ID.fullmatch(subject):
            raise ValueError("Provider subject invalid")
        if (
            not isinstance(returned_email, str)
            or returned_email.casefold() != email.casefold()
            or result.get("roles") not in ([], "")
        ):
            raise ValueError("Provider identity mismatch")
        return ProviderUser(subject)


class RauthyInvitationProvider:
    def __init__(self, lookup: InvitationLookupTransport) -> None:
        self._lookup = lookup

    def unavailable_reason(self) -> str | None:
        return provisioning_error()

    async def lookup(self, email: InvitationEmail) -> int:
        return (await self._lookup.read_by_email(email=email.value)).status

    async def create(self, email: InvitationEmail) -> ProviderUser:
        return await asyncio.to_thread(create_provider_user, email.value)
