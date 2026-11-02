"""Browser-safe Files content facade; only an independently verified owner may read.

The BFF holds an opaque Rauthy browser cookie and scoped Platform proof. It
never resolves a Project root, turns a JWT into a Cedar Permit, or invokes a
Hand via browser-supplied service headers. Missing owner port always returns
503; a source-only fixture cannot activate the real Files dataplane.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.requests import ClientDisconnect

from control_panel_api.presentation._http_errors import error_response

from ._api_paths import API_V1_PREFIX
from ._oidc_browser import (
    _SID_COOKIE,
    OidcBrowserSessionStore,
    _strict_browser_cookies,
)
from ._oidc_membership import CurrentPlatformContext
from ._oidc_origin_policy import BROWSER_ORIGIN, PUBLIC_HOST, local_browser_host
from .application.files_read import TrustedFilesContentOwner as TrustedFilesContentOwner
from .domain.files_read import FilesContentDenied as FilesContentDenied
from .domain.files_read import FilesContentUnavailable as FilesContentUnavailable
from .domain.files_read import PrivateFilesReadCommand as PrivateFilesReadCommand
from .domain.files_read import VerifiedPrivateFilesRead as VerifiedPrivateFilesRead
from .domain.files_read import canonical_files_path

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_MAX_BODY = 8192
_MAX_READ = 262_144


class BrowserFilesRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    project_uuid: UUID
    agent_session_uuid: UUID
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    path: str = Field(min_length=1, max_length=4096)
    max_bytes: int = Field(strict=True, ge=1, le=_MAX_READ)

    @field_validator("project_uuid", "agent_session_uuid", mode="before")
    @classmethod
    def canonical_uuid(cls, value: object) -> UUID:
        if not isinstance(value, str):
            raise ValueError("canonical UUID string required")
        try:
            selected = UUID(value)
        except (TypeError, ValueError):
            raise ValueError("invalid UUID string") from None
        if selected.version != 4 or str(selected) != value:
            raise ValueError("canonical UUIDv4 required")
        return selected

    @field_validator("path")
    @classmethod
    def canonical_path(cls, path: str) -> str:
        return canonical_files_path(path)


_error = error_response


def _session_cookie(request: Request) -> str | None:
    handles = _strict_browser_cookies(request)
    return handles.get(_SID_COOKIE) if handles is not None else None


async def _json_body(request: Request, *, origin: str, host: str) -> bytes | JSONResponse:
    if (
        request.headers.getlist("host") != [host]
        or request.headers.getlist("origin") != [origin]
        or request.headers.getlist("content-type") != ["application/json"]
        or request.headers.getlist("authorization")
        or request.headers.getlist("transfer-encoding")
        or request.query_params
    ):
        return _error(403, "FILES_READ_ORIGIN_DENIED")
    length = request.headers.getlist("content-length")
    if (
        len(length) != 1
        or not 1 <= len(length[0]) <= 4
        or not length[0].isascii()
        or not length[0].isdecimal()
        or not 2 <= int(length[0]) <= _MAX_BODY
    ):
        return _error(422, "FILES_READ_REQUEST_INVALID")
    received = bytearray()
    try:
        async with asyncio.timeout(5):
            async for part in request.stream():
                if len(part) > _MAX_BODY - len(received):
                    return _error(422, "FILES_READ_REQUEST_INVALID")
                received.extend(part)
    except (TimeoutError, RuntimeError, ClientDisconnect):
        return _error(422, "FILES_READ_REQUEST_INVALID")
    if len(received) != int(length[0]):
        return _error(422, "FILES_READ_REQUEST_INVALID")
    return bytes(received)


def files_content_router(
    *,
    current_context: CurrentPlatformContext,
    sessions: OidcBrowserSessionStore,
    resource_audience: str | None,
    expected_client_id: str | None,
    owner: TrustedFilesContentOwner | None,
    test_only_local_origin: str | None,
) -> APIRouter:
    from .application.files_read import ReadFiles
    from .infrastructure.files_read import CurrentFilesAuthority, StoredFilesSessions
    from .presentation.files_read import FilesReadController, FilesReadPreparation

    def use_case(request: Request) -> ReadFiles:
        return ReadFiles(
            CurrentFilesAuthority(request, current_context),
            StoredFilesSessions(sessions),
            owner,
            FilesReadPreparation(),
            audience=resource_audience,
            client_id=expected_client_id,
        )

    controller = FilesReadController(
        use_case,
        test_only_local_origin or BROWSER_ORIGIN,
        local_browser_host(test_only_local_origin) or PUBLIC_HOST,
    )
    router = APIRouter()
    router.add_api_route(
        API_V1_PREFIX + "/files/read", controller.read, methods=["POST"], include_in_schema=False
    )
    return router
