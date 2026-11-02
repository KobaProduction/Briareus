"""SVC-only unavailable transport and concrete provider policy callbacks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.websockets import WebSocket

from service_runtime.admin_api_client import AdminApiClient
from service_runtime.runtime_policy_contracts import GitHubRuntimePolicy, GitLabRuntimePolicy


async def _unavailable(_request: Request) -> Response:
    """Never echo a bearer, service ID, provider args, path or tool result."""
    return JSONResponse(
        {"code": "SVC_PRIVATE_C2_TRANSPORT_PENDING"},
        status_code=503,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def _deny_websocket(websocket: WebSocket) -> None:
    # No optional WS port may become a bypass for streamable HTTP auth/JTI.
    await websocket.close(code=1008)


@asynccontextmanager
async def _svc_lifespan(_app: Starlette) -> AsyncIterator[None]:
    """No provider clients/sessions/secrets are created or left to clean up."""
    yield


def _gitlab_runtime_policy(admin_api: AdminApiClient) -> GitLabRuntimePolicy:
    try:
        return admin_api.gitlab_runtime_policy()
    except Exception:
        return GitLabRuntimePolicy()


def _github_runtime_policy(admin_api: AdminApiClient) -> GitHubRuntimePolicy:
    try:
        return admin_api.github_runtime_policy()
    except Exception:
        return GitHubRuntimePolicy()
