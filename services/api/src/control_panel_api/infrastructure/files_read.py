"""Adapt current HTTP proof and private browser storage without performing Files effects."""

from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api.application.files_read import FilesReadFailure
from control_panel_api.domain.oidc_identity import PrivateOidcResourceCredential
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.infrastructure._oidc_bindings import _BrowserSessionRead
from control_panel_api.infrastructure.browser_sessions import ValkeyBrowserSessions


class _ErrorCode(BaseModel):
    model_config = ConfigDict(strict=True)
    code: str


class _MembershipError(BaseModel):
    error: _ErrorCode


class CurrentFilesAuthority:
    def __init__(self, request: Request, current: CurrentPlatformContext) -> None:
        self._request, self._current = request, current

    async def current(self, project: UUID) -> PanelContext | FilesReadFailure:
        context = await self._current(self._request, project)
        if isinstance(context, JSONResponse):
            error = _MembershipError.model_validate_json(bytes(context.body))
            return FilesReadFailure(context.status_code, error.error.code)
        return PanelContext(*context)


class StoredFilesSessions(_BrowserSessionRead):
    def __init__(self, sessions: ValkeyBrowserSessions) -> None:
        self._sessions = sessions

    async def credential(
        self, ticket: str, issuer: str, client_id: str, audience: str
    ) -> PrivateOidcResourceCredential | None:
        return await self._sessions.get_resource_credential(
            ticket,
            issuer=issuer,
            client_id=client_id,
            audience=audience,
        )

    session = _BrowserSessionRead._session
