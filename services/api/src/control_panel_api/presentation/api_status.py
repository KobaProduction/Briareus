"""Stable public status/configuration and fail-closed unconfigured API routes."""

from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from control_panel_api._api_paths import (
    API_V1_PREFIX,
    AUTH_API_PREFIX,
    REGISTERED_RAUTHY_CALLBACK_PATH,
)
from control_panel_api._oidc import OidcProviderUnavailable, RauthyOidcAdapter


class OidcBrowserConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None


@dataclass(frozen=True, slots=True)
class ApiLiveness:
    state: str = "live"
    service: str = "control-panel-api"
    api: str = "rauthy-oidc-bff"
    authorization: str = "fail-closed-platform-owners"


async def native_unavailable() -> Response:
    return JSONResponse(
        {"error": {"code": "NATIVE_OWNER_UNAVAILABLE"}},
        status_code=503,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def install_native_unavailable(app: FastAPI) -> None:
    for method, path in (
        ("POST", "start"),
        ("POST", "pow"),
        ("POST", "first-factor"),
        ("POST", "cancel"),
        ("GET", "capabilities"),
    ):
        app.add_api_route(
            AUTH_API_PREFIX + "/" + path,
            native_unavailable,
            methods=[method],
            include_in_schema=False,
        )


async def identity_unavailable() -> Response:
    raise HTTPException(503, detail="OIDC login is not configured")


async def platform_unavailable() -> Response:
    raise HTTPException(503, detail="OIDC Platform authority is not configured")


async def catalog_unavailable() -> Response:
    raise HTTPException(503, detail="OIDC Platform Catalog source is not configured")


async def files_unavailable() -> Response:
    return JSONResponse(
        {"error": {"code": "FILES_READ_OWNER_UNAVAILABLE"}},
        status_code=503,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def install_unconfigured(app: FastAPI) -> None:
    for method, path in (
        ("GET", AUTH_API_PREFIX + "/authorize"),
        ("GET", REGISTERED_RAUTHY_CALLBACK_PATH),
        ("GET", AUTH_API_PREFIX + "/session"),
        ("GET", AUTH_API_PREFIX + "/me"),
        ("POST", AUTH_API_PREFIX + "/logout"),
    ):
        app.add_api_route(path, identity_unavailable, methods=[method])
    for method, path in (
        ("GET", "/approvals"),
        ("POST", "/approvals"),
        ("POST", "/approvals/{approval_uuid}/resolve"),
        ("GET", "/agent-sessions"),
        ("GET", "/agent-sessions/{session_uuid}"),
        ("POST", "/agent-sessions"),
        ("POST", "/agent-sessions/{session_uuid}/revoke"),
    ):
        app.add_api_route(API_V1_PREFIX + path, platform_unavailable, methods=[method])
    app.add_api_route(
        API_V1_PREFIX + "/files/read", files_unavailable, methods=["POST"], include_in_schema=False
    )
    app.add_api_route(API_V1_PREFIX + "/catalog", catalog_unavailable, methods=["GET"])


def install_public_status(app: FastAPI, provider: RauthyOidcAdapter | None) -> None:
    @app.get("/health/live", include_in_schema=False)
    async def live() -> ApiLiveness:
        return ApiLiveness()

    @app.get(AUTH_API_PREFIX + "/config", response_model=OidcBrowserConfiguration)
    async def oidc_config(response: Response) -> OidcBrowserConfiguration:
        response.headers["Cache-Control"] = "no-store"
        if provider is None:
            raise HTTPException(status_code=503, detail="identity provider is not configured")
        try:
            configuration = await provider.public_configuration()
        except OidcProviderUnavailable as exc:
            raise HTTPException(status_code=503, detail="identity provider unavailable") from exc
        return OidcBrowserConfiguration(
            issuer=configuration.issuer,
            client_id=configuration.client_id,
            authorization_endpoint=configuration.authorization_endpoint,
            token_endpoint=configuration.token_endpoint,
            jwks_uri=configuration.jwks_uri,
            userinfo_endpoint=configuration.userinfo_endpoint,
        )
