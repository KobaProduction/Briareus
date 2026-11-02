from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from common.access_contracts import (
    AccessLevel,
    AccessRequests,
    AccessRequestView,
    AccessSessions,
    AccountScope,
    AdminResolveRequest,
    AdminSessionOwnerRequest,
    AdminSessionUpdate,
    EmptyAccessResponse,
    EnforcementMode,
    ResolvedAccessRequest,
    SessionSnapshot,
    SurfaceControlBatchUpdate,
    SurfaceControls,
    SurfaceControlUpdate,
    SurfaceControlView,
    UserControls,
    UserControlView,
)

from ._adapter_resources import _AuthorizationClient


class AuthorizationAccessAdminClient(_AuthorizationClient):
    async def _request[Result: BaseModel](
        self, method: str, path: str, response_model: type[Result], *, body: BaseModel | None = None
    ) -> Result:
        response = await self._client.request(
            method, path, json=body.model_dump(mode="json") if body is not None else None
        )
        response.raise_for_status()
        if response.status_code == 204:
            return response_model.model_validate({})
        return response_model.model_validate_json(response.content)

    async def sessions(self, user_id: UUID) -> list[SessionSnapshot]:
        result = await self._request("GET", f"/v1/admin/users/{user_id}/sessions", AccessSessions)
        return result.sessions

    async def requests(self, user_id: UUID) -> list[AccessRequestView]:
        result = await self._request("GET", f"/v1/admin/users/{user_id}/requests", AccessRequests)
        return result.requests

    async def controls(self, user_id: UUID) -> list[SurfaceControlView]:
        result = await self._request("GET", f"/v1/admin/users/{user_id}/controls", SurfaceControls)
        return result.controls

    async def resolve_request(
        self,
        request_id: UUID,
        *,
        admin_user_id: UUID,
        approve: bool,
        account_scope: AccountScope | None,
        account_ids: list[str] | None,
        expires_at: int | None,
    ) -> ResolvedAccessRequest:
        return await self._request(
            "POST",
            f"/v1/admin/requests/{request_id}/resolve",
            ResolvedAccessRequest,
            body=AdminResolveRequest(
                admin_user_id=str(admin_user_id),
                approve=approve,
                account_scope=account_scope,
                account_ids=account_ids,
                expires_at=expires_at,
            ),
        )

    async def update_session(
        self,
        session_id: UUID,
        *,
        admin_user_id: UUID,
        access_level: AccessLevel | None = None,
        account_scope: AccountScope | None = None,
        account_ids: list[str] | None = None,
        expires_at: int | None = None,
        label: str | None = None,
    ) -> SessionSnapshot:
        return await self._request(
            "PATCH",
            f"/v1/admin/sessions/{session_id}",
            SessionSnapshot,
            body=AdminSessionUpdate(
                admin_user_id=str(admin_user_id),
                access_level=access_level,
                account_scope=account_scope,
                account_ids=account_ids,
                expires_at=expires_at,
                label=label,
            ),
        )

    async def revoke_session(self, session_id: UUID, *, admin_user_id: UUID) -> None:
        await self._request(
            "POST",
            f"/v1/admin/sessions/{session_id}/revoke",
            EmptyAccessResponse,
            body=AdminSessionOwnerRequest(admin_user_id=str(admin_user_id)),
        )

    async def set_controls(
        self, *, user_id: UUID, items: list[tuple[int, EnforcementMode]]
    ) -> list[UserControlView]:
        result = await self._request(
            "PUT",
            "/v1/admin/controls/batch",
            UserControls,
            body=SurfaceControlBatchUpdate(
                items=[
                    SurfaceControlUpdate(user_id=str(user_id), surface_id=surface_id, mode=mode)
                    for surface_id, mode in items
                ]
            ),
        )
        return result.controls
