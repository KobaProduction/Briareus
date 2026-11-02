"""Cookie parsing and HTTP error adaptation for current membership use cases."""

from uuid import UUID

from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection

from control_panel_api._oidc_browser import _SID_COOKIE, _TOKEN, _strict_browser_cookies
from control_panel_api.application.platform_membership import CurrentMembership, MembershipFailure
from control_panel_api.domain.platform_authority import PanelOidcSession, ResolvedPlatformUser


class MembershipController:
    def __init__(self, membership: CurrentMembership, *, expected_host: str | None) -> None:
        self._membership = membership
        self._host = expected_host

    @staticmethod
    def _failure(failure: MembershipFailure) -> JSONResponse:
        response = JSONResponse(
            {"error": {"code": failure.code}},
            status_code=failure.status,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
        if failure.clear_cookie:
            response.delete_cookie(
                _SID_COOKIE, path="/", secure=True, httponly=True, samesite="lax"
            )
        return response

    async def __call__(
        self, request: HTTPConnection, project_uuid: UUID | None = None
    ) -> tuple[PanelOidcSession, ResolvedPlatformUser] | JSONResponse:
        if self._host is not None and request.headers.getlist("host") != [self._host]:
            return self._failure(MembershipFailure(403, "LOCAL_OIDC_BROWSER_HOST_MISMATCH"))
        handles = _strict_browser_cookies(request)
        ticket = handles.get(_SID_COOKIE, "") if handles is not None else ""
        if _TOKEN.fullmatch(ticket) is None:
            return self._failure(MembershipFailure(401, "OIDC_SESSION_REQUIRED"))
        result = await self._membership.resolve(ticket, project_uuid)
        if isinstance(result, MembershipFailure):
            return self._failure(result)
        return result.session, result.user
