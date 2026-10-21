"""Pinned Rauthy ce35a70f magic-link setup/reset inside Control Panel.

GET /users/{id}/reset/{code} with JSON Accept returns CSRF + reset cookie;
PUT /users/{id}/reset consumes both. Provider alone applies password rules,
sets email_verified, invalidates sessions and expires/invalidates magic links.
"""
import asyncio
import json
import logging
import re
import secrets
import os
import time
from http.cookies import SimpleCookie

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from valkey.exceptions import ValkeyError

from ._api_paths import AUTH_API_PREFIX
from ._oidc import _unique_oidc_fields
from ._local_provider_transport import provider_http_client
from ._oidc_browser import _SETUP_COOKIE, _cookie, _clear, _strict_browser_cookies
from ._oidc_origin_policy import resolve_browser_origin, local_browser_host, PUBLIC_HOST


class _NoMagicLinkLogs(logging.Filter):
    def filter(self, record):
        # HTTPX INFO request URLs would otherwise expose a bearer magic link.
        return "/reset/" not in record.getMessage()


logging.getLogger("httpx").addFilter(_NoMagicLinkLogs())


class SetupCode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: str = Field(pattern=r"^[A-Za-z0-9]{24}$")
    code: SecretStr


class SetupPassword(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    password: SecretStr


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    pow: SecretStr


def password_setup_router(*, native, provider, sessions, test_only_local_origin):
    router = APIRouter(prefix=AUTH_API_PREFIX + "/password-setup")
    origin = resolve_browser_origin(test_origin=test_only_local_origin, provider_issuer=provider.issuer, provider_client=provider.client_id)
    host = local_browser_host(test_only_local_origin) or PUBLIC_HOST

    def reply(status, **body):
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    async def body(request, model):
        if (request.headers.getlist("origin") != [origin] or request.headers.getlist("host") != [host]
            or request.headers.getlist("content-type") != ["application/json"] or request.query_params
            or request.headers.getlist("authorization") or request.headers.getlist("transfer-encoding")
            or len(request.headers.getlist("content-length")) != 1
            or request.headers.get("sec-fetch-site") not in (None, "same-origin")
            or _strict_browser_cookies(request) is None):
            raise ValueError()
        data = bytearray()
        async with asyncio.timeout(5):
            async for part in request.stream():
                if len(data) + len(part) > 4096:
                    raise ValueError()
                data.extend(part)
        return model.model_validate(json.loads(data, object_pairs_hook=_unique_oidc_fields))

    @router.post("/recovery-pow")
    async def recovery_pow(request: Request):
        try:
            await body(request, EmptyRequest)
            if os.environ.get("RAUTHY_INVITATION_EMAIL_READY") != "1":
                return reply(503, error={"code": "RAUTHY_INVITATION_MAIL_UNCONFIGURED"})
            return reply(200, challenge=await native.issue_pow())
        except (ValueError, TimeoutError):
            return reply(422, error={"code": "SETUP_REQUEST_INVALID"})
        except Exception:
            return reply(503, error={"code": "SETUP_PROVIDER_UNAVAILABLE"})

    @router.post("/recovery-request")
    async def recovery_request(request: Request):
        try:
            data = await body(request, RecoveryRequest)
            if os.environ.get("RAUTHY_INVITATION_EMAIL_READY") != "1":
                return reply(503, error={"code": "RAUTHY_INVITATION_MAIL_UNCONFIGURED"})
            if data.email.count("@") != 1 or any(ord(c) < 33 for c in data.email) or len(data.pow.get_secret_value()) > 256:
                raise ValueError()
            async with provider_http_client(verify=native._tls, timeout=5) as client:
                async with client.stream("POST", native.issuer + "/users/request_reset", headers={"Accept": "application/json"},
                    json={"email": data.email, "pow": data.pow.get_secret_value(), "redirect_uri": None}) as response:
                    if response.status_code != 200:
                        return reply(400, error={"code": "RECOVERY_PROVIDER_REJECTED"})
            return reply(200, accepted=True, delivery="unconfirmed")
        except (ValueError, TypeError, TimeoutError):
            return reply(422, error={"code": "SETUP_REQUEST_INVALID"})
        except httpx.HTTPError:
            return reply(503, error={"code": "SETUP_PROVIDER_UNAVAILABLE"})

    @router.post("/prepare")
    async def prepare(request: Request):
        try:
            data = await body(request, SetupCode)
            code = data.code.get_secret_value()
            if re.fullmatch(r"[A-Za-z0-9]{64}", code, re.ASCII) is None:
                raise ValueError()
            prior = _strict_browser_cookies(request).get(_SETUP_COOKIE)
            headers = {"Accept": "application/json"}
            if prior:
                previous = await sessions._client.get(sessions._key("password-setup", prior))
                if isinstance(previous, str):
                    previous = json.loads(previous)
                    if previous["user_id"] == data.user_id and previous["code"] == code:
                        headers["Cookie"] = previous["cookie"]
            async with provider_http_client(verify=native._tls, timeout=5) as client:
                async with client.stream("GET", native.issuer + "/users/" + data.user_id + "/reset/" + code,
                                         headers=headers) as response:
                    if response.status_code != 200:
                        return reply(400, error={"code": "SETUP_CODE_INVALID_OR_EXPIRED"})
                    if response.headers.get("content-type", "").split(";")[0] != "application/json":
                        raise ValueError()
                    content = bytearray()
                    async for part in response.aiter_bytes():
                        if len(content) + len(part) > 8192:
                            raise ValueError()
                        content.extend(part)
                    parsed = json.loads(content)
                    csrf = parsed.get("csrf_token")
                    if not isinstance(csrf, str) or re.fullmatch(r"[A-Za-z0-9]{48}", csrf) is None:
                        raise ValueError()
                    cookies = SimpleCookie()
                    for item in response.headers.get_list("set-cookie"):
                        cookies.load(item)
                    reset = cookies.get("rauthy-pwd-reset") or cookies.get("__Host-rauthy-pwd-reset")
                    if reset is None or re.fullmatch(r"[A-Za-z0-9]{48}", reset.value) is None:
                        raise ValueError()
                    age = min(300, int(reset["max-age"]))
                    if age < 1 or not isinstance(parsed.get("password_policy"), dict):
                        raise ValueError()
                    ticket = secrets.token_urlsafe(32)
                    saved = await sessions._client.set(sessions._key("password-setup", ticket), json.dumps({
                        "user_id": data.user_id, "code": code, "csrf": csrf,
                        "cookie": reset.key + "=" + reset.value, "expires_at": time.time() + age}), ex=age, nx=True)
                    if not saved:
                        raise ValkeyError("Setup state not saved")
                    if prior:
                        await sessions._client.delete(sessions._key("password-setup", prior))
                    result = reply(200, prepared=True, expires_in=age, password_policy=parsed["password_policy"])
                    _cookie(result, _SETUP_COOKIE, ticket, age)
                    return result
        except (ValueError, TypeError, KeyError):
            return reply(422, error={"code": "SETUP_REQUEST_OR_PROVIDER_RESPONSE_INVALID"})
        except (httpx.HTTPError, ValkeyError, TimeoutError):
            return reply(503, error={"code": "SETUP_PROVIDER_UNAVAILABLE"})

    @router.post("/finish")
    async def finish(request: Request):
        try:
            data = await body(request, SetupPassword)
            password = data.password.get_secret_value()
            if not 1 <= len(password) <= 256:
                raise ValueError()
            ticket = _strict_browser_cookies(request).get(_SETUP_COOKIE)
            if not ticket:
                return reply(401, error={"code": "SETUP_PREPARATION_REQUIRED"})
            # One in-flight submission per browser preparation, including tabs.
            raw = await sessions._client.getdel(sessions._key("password-setup", ticket))
            if not isinstance(raw, str):
                return reply(401, error={"code": "SETUP_PREPARATION_EXPIRED"})
            private = json.loads(raw)
            async with provider_http_client(verify=native._tls, timeout=8) as client:
                async with client.stream("PUT", native.issuer + "/users/" + private["user_id"] + "/reset",
                    headers={"Accept": "application/json", "Cookie": private["cookie"], "x-pwd-csrf-token": private["csrf"]},
                    json={"magic_link_id": private["code"], "password": password, "mfa_code": None}) as response:
                    status = response.status_code
            # Never follow an upstream location back to its hosted screens.
            if status == 202:
                result = reply(200, completed=True)
                _clear(result, _SETUP_COOKIE)
            else:
                # A rejected password does not consume the provider's magic
                # link. Retain its binding cookie so re-preparation can work;
                # never extend the original short preparation lifetime.
                remaining = int(private["expires_at"] - time.time())
                if remaining > 0:
                    await sessions._client.set(sessions._key("password-setup", ticket), raw, ex=remaining, nx=True)
                result = reply(400, error={"code": "SETUP_PROVIDER_REJECTED"})
            return result
        except (ValueError, TypeError, KeyError):
            return reply(422, error={"code": "SETUP_REQUEST_INVALID"})
        except (httpx.HTTPError, ValkeyError, TimeoutError):
            return reply(503, error={"code": "SETUP_OUTCOME_UNCONFIRMED"})

    return router
