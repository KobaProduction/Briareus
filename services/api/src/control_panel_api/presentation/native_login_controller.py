"""Bounded native-login HTTP boundary; lifecycle belongs to application."""

from __future__ import annotations

import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from control_panel_api._oidc_browser import _NATIVE_TX_COOKIE, _clear, _strict_browser_cookies
from control_panel_api.application.native_login import NativeLogin
from control_panel_api.domain.native_login import NativeCredentials
from control_panel_api.infrastructure.json_fields import validate_unique_fields

from ._bindings import _NativeControllerBinding
from .native_login import NO_STORE, native_login_response


def _failure(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=NO_STORE)


class NativeOtpMethodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    method_index: int = Field(ge=0, le=9)


class NativeOtpFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    otp_code: SecretStr

    @field_validator("otp_code")
    @classmethod
    def validate_otp_value(cls, value: SecretStr) -> SecretStr:
        import re

        original = value.get_secret_value()
        compact = original.replace(" ", "")
        if re.fullmatch(r"[0-9]{6,8}", compact, re.ASCII) is None:
            raise ValueError("OTP verification code has unsupported shape")
        if original != compact and original != (
            compact[: len(compact) // 2] + " " + compact[len(compact) // 2 :]
        ):
            raise ValueError("OTP formatted code is ambiguous")
        # Rauthy emails codes in two groups separated by ONE ASCII space;
        # its actual v0.37.1 validate() expects the original digits only.
        return SecretStr(compact)


class NativeLoginController(_NativeControllerBinding[NativeLogin]):
    async def read_body(self, request: Request, *, empty: bool) -> bytes | JSONResponse:
        if (
            request.headers.getlist("origin") != [self._origin]
            or request.headers.getlist("host") != [self._host]
            or request.headers.getlist("content-type") != ["application/json"]
            or request.headers.getlist("authorization")
            or request.headers.getlist("transfer-encoding")
            or len(request.headers.getlist("cookie")) > 1
            or request.query_params
        ):
            return _failure(403, "NATIVE_ORIGIN_OR_REQUEST_DENIED")
        lengths = request.headers.getlist("content-length")
        if (
            len(lengths) != 1
            or not 1 <= len(lengths[0]) <= 4
            or not lengths[0].isascii()
            or not lengths[0].isdecimal()
            or not 2 <= int(lengths[0]) <= 8192
        ):
            return _failure(422, "NATIVE_REQUEST_INVALID")
        content = bytearray()
        try:
            async with asyncio.timeout(5):
                async for block in request.stream():
                    if len(content) + len(block) > 8192:
                        return _failure(422, "NATIVE_REQUEST_INVALID")
                    content.extend(block)
        except (TimeoutError, RuntimeError):
            return _failure(422, "NATIVE_REQUEST_INVALID")
        if len(content) != int(lengths[0]) or (empty and bytes(content) != b"{}"):
            return _failure(422, "NATIVE_REQUEST_INVALID")
        return bytes(content)

    def _state(self, request: Request) -> str | JSONResponse:
        handles = _strict_browser_cookies(request)
        if handles is None:
            return _failure(401, "NATIVE_COOKIE_INVALID")
        state = handles.get(_NATIVE_TX_COOKIE)
        return state if state is not None else _failure(401, "NATIVE_INIT_REQUIRED")

    async def capabilities(self, request: Request) -> Response:
        if request.headers.getlist("host") != [self._host] or request.query_params:
            return _failure(403, "NATIVE_ORIGIN_OR_REQUEST_DENIED")
        # Current deployed UI only accepts []; OTP remains private until coordinated release.
        return JSONResponse(
            {
                "protocol": "rauthy-native-v1",
                "first_factor": "password",
                "pow": "client-solved",
                "cancel": True,
                "continuations": [],
            },
            headers=NO_STORE,
        )

    async def cancel(self, request: Request) -> Response:
        body = await self.read_body(request, empty=True)
        if isinstance(body, JSONResponse):
            return body
        handles = _strict_browser_cookies(request)
        if handles is None:
            return _failure(401, "NATIVE_COOKIE_INVALID")
        state = handles.get(_NATIVE_TX_COOKIE)
        if state is not None and not await self._login.retire(state):
            return _failure(503, "NATIVE_CANCEL_UNAVAILABLE")
        response = Response(status_code=204, headers=NO_STORE)
        _clear(response, _NATIVE_TX_COOKIE)
        return response

    async def _body[Model: BaseModel](
        self, request: Request, model: type[Model], *, error: str
    ) -> Model | JSONResponse:
        raw = await self.read_body(request, empty=False)
        if isinstance(raw, JSONResponse):
            return raw
        try:
            validate_unique_fields(raw)
            return model.model_validate_json(raw)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return _failure(422, error)

    async def first_factor(self, request: Request) -> Response:
        from control_panel_api._native_credentials import NativeFirstFactorRequest

        credentials = await self._body(
            request, NativeFirstFactorRequest, error="NATIVE_REQUEST_INVALID"
        )
        if isinstance(credentials, JSONResponse):
            return credentials
        state = self._state(request)
        if isinstance(state, JSONResponse):
            return state
        result = await self._login.first_factor(
            state,
            NativeCredentials(credentials.email, credentials.password, credentials.pow),
            request,
        )
        return native_login_response(result)

    async def otp_start(self, request: Request) -> Response:
        body = await self._body(request, NativeOtpMethodRequest, error="NATIVE_OTP_REQUEST_INVALID")
        if isinstance(body, JSONResponse):
            return body
        state = self._state(request)
        if isinstance(state, JSONResponse):
            return state
        return native_login_response(await self._login.otp_start(state, body.method_index, request))

    async def otp_finish(self, request: Request) -> Response:
        body = await self._body(request, NativeOtpFinishRequest, error="NATIVE_OTP_REQUEST_INVALID")
        if isinstance(body, JSONResponse):
            return body
        state = self._state(request)
        if isinstance(state, JSONResponse):
            return state
        return native_login_response(
            await self._login.otp_finish(state, body.otp_code.get_secret_value(), request)
        )
