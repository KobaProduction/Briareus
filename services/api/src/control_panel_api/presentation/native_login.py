"""HTTP serialization for typed native-login outcomes."""

from dataclasses import asdict, dataclass, field
from typing import Literal

from fastapi.responses import JSONResponse, Response

from control_panel_api._oidc_browser import _SID_COOKIE, _cookie
from control_panel_api.domain.native_login import NativeLoginResult, OtpKind

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@dataclass(frozen=True, slots=True)
class _ErrorCode:
    code: str


@dataclass(frozen=True, slots=True)
class _Failure:
    error: _ErrorCode


@dataclass(frozen=True, slots=True)
class _RateLimitedFailure(_Failure):
    retry_not_before: int | None


@dataclass(frozen=True, slots=True)
class _Authenticated:
    stage: Literal["authenticated"] = "authenticated"
    authenticated: Literal[True] = True
    authority: Literal["rauthy"] = "rauthy"
    platform_membership_verified: Literal[False] = False
    permissions: tuple[()] = ()


@dataclass(frozen=True, slots=True)
class _AnonymousStage:
    stage: str
    authenticated: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class _FirstFactor(_AnonymousStage):
    expires_in: int | None


@dataclass(frozen=True, slots=True)
class _Challenge:
    challenge: str
    authenticated: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class _OtpPending(_AnonymousStage):
    expires_at: int | None


@dataclass(frozen=True, slots=True)
class _Restart(_AnonymousStage):
    continuation_available: Literal[False] = field(default=False, init=False)
    restart_required: Literal[True] = field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class _Method:
    index: int
    kind: OtpKind


@dataclass(frozen=True, slots=True)
class _Continuation(_AnonymousStage):
    continuation_available: bool
    methods: tuple[_Method, ...]


type _NativePayload = (
    _Failure
    | _RateLimitedFailure
    | _Authenticated
    | _FirstFactor
    | _Challenge
    | _OtpPending
    | _Restart
    | _Continuation
)


def _native_json(payload: _NativePayload, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(asdict(payload), status_code=status_code, headers=NO_STORE)


def native_login_response(result: NativeLoginResult) -> Response:
    if result.error_code is not None:
        code = _ErrorCode(result.error_code)
        if result.status == 429:
            payload: _Failure = _RateLimitedFailure(code, result.retry_not_before)
        else:
            payload = _Failure(code)
        return _native_json(payload, status_code=result.status)
    if result.stage == "authenticated":
        response = _native_json(_Authenticated())
        if result.ticket is None:
            raise ValueError("authenticated outcome lacks a private session ticket")
        _cookie(response, _SID_COOKIE, result.ticket, result.session_seconds)
        return response
    if result.stage == "first_factor_required":
        response = _native_json(_FirstFactor(result.stage, result.expires_in), status_code=201)
        if result.ticket is None or result.expires_in is None:
            raise ValueError("initial login outcome lacks its pending transaction")
        from control_panel_api._oidc_browser import _NATIVE_TX_COOKIE

        _cookie(response, _NATIVE_TX_COOKIE, result.ticket, result.expires_in)
        return response
    if result.challenge is not None:
        return _native_json(_Challenge(result.challenge))
    if result.stage == "otp_code_pending":
        return _native_json(_OtpPending(result.stage, result.expires_at), status_code=result.status)
    if result.restart_required:
        return _native_json(_Restart(result.stage), status_code=result.status)
    return _native_json(
        _Continuation(
            result.stage,
            result.continuation_available,
            tuple(_Method(index, kind) for index, kind in enumerate(result.methods)),
        ),
        status_code=result.status,
    )
