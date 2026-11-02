"""Authoritative legacy HTTP validation adapter with redacted availability errors."""

import httpx

from bridge.application.access_session import AccessValidationUnavailable
from bridge.infrastructure.access_client import AuthorizationAccessClient
from common.access_contracts import OAuthContext, ValidationResult
from service_runtime._reference_bindings import _ClientBinding


class HttpSessionValidation(_ClientBinding[AuthorizationAccessClient]):
    async def validate(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        tool_name: str,
        requires_full_access: bool,
        account_id: str,
    ) -> ValidationResult:
        try:
            return await self._client.validate(
                context=context,
                surface_id=surface_id,
                session_uid=session_uid,
                tool_name=tool_name,
                requires_full_access=requires_full_access,
                account_id=account_id,
            )
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            raise AccessValidationUnavailable(type(exc).__name__) from exc
