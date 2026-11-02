"""Application-owned OAuth adapters around maintained FastMCP provider contracts."""

from __future__ import annotations

import hmac

from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import AccessToken, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .provider import MultiResourceZitadelProvider


class RevocationForm(BaseModel):
    model_config = ConfigDict(extra="ignore")
    token: str = Field(min_length=1, repr=False)
    client_id: str | None = None
    client_secret: str | None = Field(None, repr=False)
    token_type_hint: str | None = None


class IntrospectionForm(BaseModel):
    model_config = ConfigDict(extra="ignore")
    token: str = Field(min_length=1, repr=False)


class OAuthRouteError(BaseModel):
    error: str
    error_description: str


def oauth_error(status: int, error: str, description: str) -> JSONResponse:
    payload = OAuthRouteError(error=error, error_description=description)
    return JSONResponse(
        payload.model_dump(), status_code=status, headers={"Cache-Control": "no-store"}
    )


class OAuthRoutes:
    def __init__(self, provider: MultiResourceZitadelProvider) -> None:
        self.provider = provider
        self.authenticator = ClientAuthenticator(provider)

    async def _revocation_token(
        self,
        client: OAuthClientInformationFull,
        form: RevocationForm,
    ) -> AccessToken | RefreshToken | None:
        if form.token_type_hint == "refresh_token":
            refresh = await self.provider.load_refresh_token(client, form.token)
            return refresh or await self.provider.load_access_token(form.token)
        access = await self.provider.load_access_token(form.token)
        return access or await self.provider.load_refresh_token(client, form.token)

    async def revoke(self, request: Request) -> Response:
        try:
            client = await self.authenticator.authenticate_request(request)
        except AuthenticationError:
            return oauth_error(401, "unauthorized_client", "OAuth client authentication failed")
        try:
            form = RevocationForm.model_validate(dict(await request.form()))
        except ValidationError:
            return oauth_error(400, "invalid_request", "Invalid token revocation parameters")
        if form.client_id is not None and form.client_id != client.client_id:
            return oauth_error(401, "unauthorized_client", "OAuth client identity does not match")
        token = await self._revocation_token(client, form)
        if token is not None and token.client_id == client.client_id:
            await self.provider.revoke_token(token)
        return Response(
            status_code=200, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
        )

    async def introspect(self, request: Request) -> Response:
        supplied = request.headers.get("authorization", "")
        secret = self.provider.settings.resolved_introspection_token
        expected = "Bearer " + secret
        if not secret or not hmac.compare_digest(supplied, expected):
            return oauth_error(401, "invalid_client", "Private token-status credential is required")
        try:
            form = IntrospectionForm.model_validate(dict(await request.form()))
        except ValidationError:
            return oauth_error(400, "invalid_request", "Invalid token introspection parameters")
        status = await self.provider.token_authority.status(form.token)
        return JSONResponse(
            status.model_dump(exclude_none=True),
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
