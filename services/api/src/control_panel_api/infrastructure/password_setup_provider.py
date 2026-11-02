"""Pinned Rauthy reset protocol; provider alone validates and changes credentials."""

import logging
import re
from http.cookies import SimpleCookie

import httpx
from pydantic import BaseModel, SecretStr

from control_panel_api._local_provider_transport import provider_http_client
from control_panel_api._rauthy_native_init import PinnedNativeRauthyInit
from control_panel_api.application.password_setup import (
    PreparedProviderReset,
    ProviderPasswordPolicy,
)
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.password_setup import PasswordPreparation, PasswordSetupUnavailable
from control_panel_api.infrastructure._oidc_bindings import _NativePow


class _NoMagicLinkLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/reset/" not in record.getMessage()


logging.getLogger("httpx").addFilter(_NoMagicLinkLogs())


class ResetProviderReply(BaseModel):
    csrf_token: str
    password_policy: ProviderPasswordPolicy


def _reset_cookie(headers: httpx.Headers) -> tuple[SecretStr, int]:
    cookies = SimpleCookie()
    for item in headers.get_list("set-cookie"):
        cookies.load(item)
    reset = cookies.get("rauthy-pwd-reset") or cookies.get("__Host-rauthy-pwd-reset")
    if reset is None or re.fullmatch(r"[A-Za-z0-9]{48}", reset.value) is None:
        raise ValueError("Invalid provider reset cookie")
    age = min(300, int(reset["max-age"]))
    if age < 1:
        raise ValueError("Invalid provider reset cookie lifetime")
    return SecretStr(reset.key + "=" + reset.value), age


async def _preparation(response: httpx.Response) -> PreparedProviderReset:
    if response.headers.get("content-type", "").split(";")[0] != "application/json":
        raise ValueError("Invalid provider reset response")
    content = bytearray()
    async for part in response.aiter_bytes():
        if len(content) + len(part) > 8192:
            raise ValueError("Invalid provider reset response")
        content.extend(part)
    parsed = ResetProviderReply.model_validate_json(content)
    if re.fullmatch(r"[A-Za-z0-9]{48}", parsed.csrf_token) is None:
        raise ValueError("Invalid provider reset CSRF")
    cookie, age = _reset_cookie(response.headers)
    return PreparedProviderReset(SecretStr(parsed.csrf_token), cookie, age, parsed.password_policy)


class RauthyPasswordSetupProvider(_NativePow):
    def __init__(self, native: PinnedNativeRauthyInit) -> None:
        self._native = native

    async def request_recovery(self, email: str, pow_solution: SecretText) -> bool:
        try:
            async with (
                provider_http_client(verify=self._native._tls, timeout=5) as client,
                client.stream(
                    "POST",
                    self._native.issuer + "/users/request_reset",
                    headers={"Accept": "application/json"},
                    json={
                        "email": email,
                        "pow": pow_solution.get_secret_value(),
                        "redirect_uri": None,
                    },
                ) as response,
            ):
                return response.status_code == 200
        except httpx.HTTPError:
            raise PasswordSetupUnavailable from None

    async def prepare(
        self,
        user_id: str,
        code: SecretText,
        prior_cookie: SecretText | None,
    ) -> PreparedProviderReset | None:
        headers = {"Accept": "application/json"}
        if prior_cookie is not None:
            headers["Cookie"] = prior_cookie.get_secret_value()
        try:
            async with (
                provider_http_client(verify=self._native._tls, timeout=5) as client,
                client.stream(
                    "GET",
                    self._native.issuer + "/users/" + user_id + "/reset/" + code.get_secret_value(),
                    headers=headers,
                ) as response,
            ):
                if response.status_code != 200:
                    return None
                return await _preparation(response)
        except httpx.HTTPError:
            raise PasswordSetupUnavailable from None

    async def finish(self, preparation: PasswordPreparation, password: SecretText) -> bool:
        try:
            async with (
                provider_http_client(verify=self._native._tls, timeout=8) as client,
                client.stream(
                    "PUT",
                    self._native.issuer + "/users/" + preparation.user_id + "/reset",
                    headers={
                        "Accept": "application/json",
                        "Cookie": preparation.cookie.get_secret_value(),
                        "x-pwd-csrf-token": preparation.csrf.get_secret_value(),
                    },
                    json={
                        "magic_link_id": preparation.code.get_secret_value(),
                        "password": password.get_secret_value(),
                        "mfa_code": None,
                    },
                ) as response,
            ):
                return response.status_code == 202
        except httpx.HTTPError:
            raise PasswordSetupUnavailable from None
