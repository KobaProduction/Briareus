from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from common.access_contracts import (
    AccessRequestView,
    AccountScope,
    ExtensionRequest,
    FullAccessRequest,
    OAuthContext,
    SessionOpenRequest,
    SessionSnapshot,
    SessionUpdateRequest,
    SessionValidateRequest,
    ValidationResult,
)
from common.settings import AuthorizationAccessClientSettings
from service_runtime._async_http_lifecycle import _AsyncClientClose


class SurfaceSessionRequest(OAuthContext):
    surface_id: int
    session_uid: str = Field(min_length=16, max_length=256)


class AuthorizationAccessClient(_AsyncClientClose):
    def __init__(self, settings: AuthorizationAccessClientSettings | None = None) -> None:
        self.settings = settings or AuthorizationAccessClientSettings()
        self._client = httpx.AsyncClient(
            base_url=self.settings.url.rstrip("/"),
            timeout=self.settings.timeout_seconds,
            headers={"Authorization": f"Bearer {self.settings.service_token}"},
        )

    async def _post[T: BaseModel](
        self,
        path: str,
        payload: BaseModel,
        result_type: type[T],
    ) -> T:
        response = await self._client.post(path, json=payload.model_dump(mode="json"))
        response.raise_for_status()
        return result_type.model_validate_json(response.content)

    async def open(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        label: str = "",
    ) -> SessionSnapshot:
        return await self._post(
            "/v1/session/open",
            SessionOpenRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                label=label,
            ),
            SessionSnapshot,
        )

    async def validate(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        tool_name: str,
        requires_full_access: bool,
        account_id: str = "",
    ) -> ValidationResult:
        return await self._post(
            "/v1/session/validate",
            SessionValidateRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                session_uid=session_uid,
                tool_name=tool_name,
                requires_full_access=requires_full_access,
                account_id=account_id,
            ),
            ValidationResult,
        )

    async def status(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
    ) -> SessionSnapshot:
        return await self._post(
            "/v1/session/status",
            SurfaceSessionRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                session_uid=session_uid,
            ),
            SessionSnapshot,
        )

    async def update(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        label: str,
    ) -> SessionSnapshot:
        return await self._post(
            "/v1/session/update",
            SessionUpdateRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                session_uid=session_uid,
                label=label,
            ),
            SessionSnapshot,
        )

    async def request_full_access(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        account_scope: AccountScope,
        account_ids: list[str],
    ) -> AccessRequestView:
        return await self._post(
            "/v1/session/request-full-access",
            FullAccessRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                session_uid=session_uid,
                account_scope=account_scope,
                account_ids=account_ids,
            ),
            AccessRequestView,
        )

    async def request_extension(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        requested_expires_at: int,
    ) -> AccessRequestView:
        return await self._post(
            "/v1/session/request-extension",
            ExtensionRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                session_uid=session_uid,
                requested_expires_at=requested_expires_at,
            ),
            AccessRequestView,
        )

    async def close_session(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
    ) -> SessionSnapshot:
        return await self._post(
            "/v1/session/close",
            SurfaceSessionRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                session_uid=session_uid,
            ),
            SessionSnapshot,
        )

    async def reissue(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        label: str = "",
    ) -> SessionSnapshot:
        return await self._post(
            "/v1/session/reissue",
            SessionUpdateRequest(
                user_id=context.user_id,
                client_id=context.client_id,
                oauth_session_id=context.oauth_session_id,
                surface_id=surface_id,
                session_uid=session_uid,
                label=label,
            ),
            SessionSnapshot,
        )
