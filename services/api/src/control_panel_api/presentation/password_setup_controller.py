"""Bounded same-origin request adaptation and public reset response/cookie policy."""

import asyncio
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from control_panel_api._oidc_browser import _SETUP_COOKIE, _clear, _cookie, _strict_browser_cookies
from control_panel_api.application.password_setup import PasswordSetup
from control_panel_api.domain.password_setup import PasswordSetupDenied, PasswordSetupUnavailable
from control_panel_api.infrastructure.json_fields import validate_unique_fields
from control_panel_api.presentation._http_errors import error_response
from control_panel_api.presentation.password_setup_models import (
    EmptyRequest,
    RecoveryRequest,
    SetupCode,
    SetupPassword,
)

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


_failure = error_response


@dataclass(frozen=True, slots=True)
class SetupRequest[Model: BaseModel]:
    data: Model
    prior_ticket: str | None


class PasswordSetupController:
    def __init__(self, setup: PasswordSetup, *, origin: str, host: str) -> None:
        self._setup = setup
        self._origin = origin
        self._host = host

    def _headers_valid(self, request: Request) -> bool:
        return (
            request.headers.getlist("origin") == [self._origin]
            and request.headers.getlist("host") == [self._host]
            and request.headers.getlist("content-type") == ["application/json"]
            and not request.query_params
            and not request.headers.getlist("authorization")
            and not request.headers.getlist("transfer-encoding")
            and len(request.headers.getlist("content-length")) == 1
            and request.headers.get("sec-fetch-site") in (None, "same-origin")
        )

    async def _body[Model: BaseModel](
        self, request: Request, model: type[Model]
    ) -> SetupRequest[Model]:
        handles = _strict_browser_cookies(request)
        if not self._headers_valid(request) or handles is None:
            raise ValueError("Invalid password setup request")
        data = bytearray()
        async with asyncio.timeout(5):
            async for part in request.stream():
                if len(data) + len(part) > 4096:
                    raise ValueError("Invalid password setup request")
                data.extend(part)
        validate_unique_fields(data)
        parsed = model.model_validate_json(data)
        return SetupRequest(parsed, handles.get(_SETUP_COOKIE))

    async def recovery_pow(self, request: Request) -> JSONResponse:
        try:
            await self._body(request, EmptyRequest)
            challenge = await self._setup.recovery_pow()
            return JSONResponse({"challenge": challenge}, headers=_NO_STORE)
        except PasswordSetupDenied as exc:
            return _failure(exc.status, exc.code)
        except (ValueError, TimeoutError):
            return _failure(422, "SETUP_REQUEST_INVALID")
        except Exception:
            return _failure(503, "SETUP_PROVIDER_UNAVAILABLE")

    async def recovery_request(self, request: Request) -> JSONResponse:
        try:
            parsed = await self._body(request, RecoveryRequest)
            await self._setup.request_recovery(parsed.data.email, parsed.data.pow)
            return JSONResponse({"accepted": True, "delivery": "unconfirmed"}, headers=_NO_STORE)
        except PasswordSetupDenied as exc:
            return _failure(exc.status, exc.code)
        except (ValueError, TypeError, TimeoutError):
            return _failure(422, "SETUP_REQUEST_INVALID")
        except PasswordSetupUnavailable:
            return _failure(503, "SETUP_PROVIDER_UNAVAILABLE")

    async def prepare(self, request: Request) -> JSONResponse:
        try:
            parsed = await self._body(request, SetupCode)
            result = await self._setup.prepare(
                parsed.data.user_id, parsed.data.code, parsed.prior_ticket
            )
            response = JSONResponse(
                {
                    "prepared": True,
                    "expires_in": result.age,
                    "password_policy": result.policy.model_dump(exclude_unset=True),
                },
                headers=_NO_STORE,
            )
            _cookie(response, _SETUP_COOKIE, result.ticket, result.age)
            return response
        except PasswordSetupDenied as exc:
            return _failure(exc.status, exc.code)
        except (ValueError, TypeError, KeyError):
            return _failure(422, "SETUP_REQUEST_OR_PROVIDER_RESPONSE_INVALID")
        except (PasswordSetupUnavailable, TimeoutError):
            return _failure(503, "SETUP_PROVIDER_UNAVAILABLE")

    async def finish(self, request: Request) -> JSONResponse:
        try:
            parsed = await self._body(request, SetupPassword)
            await self._setup.finish(parsed.prior_ticket, parsed.data.password)
            response = JSONResponse({"completed": True}, headers=_NO_STORE)
            _clear(response, _SETUP_COOKIE)
            return response
        except PasswordSetupDenied as exc:
            return _failure(exc.status, exc.code)
        except (ValueError, TypeError, KeyError):
            return _failure(422, "SETUP_REQUEST_INVALID")
        except (PasswordSetupUnavailable, TimeoutError):
            return _failure(503, "SETUP_OUTCOME_UNCONFIRMED")
