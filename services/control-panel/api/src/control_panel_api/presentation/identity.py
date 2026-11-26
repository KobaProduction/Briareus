from __future__ import annotations

from briareus_oidc import TokenAccessDenied, VerifiedPrincipal
from briareus_oidc.gateway_contract import GatewayIdentityUnavailable
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.websockets import WebSocket

from control_panel_api.application.identity import PanelTokenIdentity

PRINCIPAL_SCOPE_KEY = "briareus.principal"
WEBSOCKET_PROTOCOL = "briareus.v1"


class IdentityState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authenticated: bool = True
    username: str
    subject: str


def bearer_token(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token or token != token.strip():
        raise ValueError("bearer token required")
    return token


def request_principal(request: Request, identity: PanelTokenIdentity) -> VerifiedPrincipal:
    cached = request.scope.get(PRINCIPAL_SCOPE_KEY)
    if isinstance(cached, VerifiedPrincipal) and cached.is_active():
        return cached
    try:
        token = bearer_token(request.headers.get("authorization", ""))
        principal = identity.verify(token)
    except TokenAccessDenied:
        raise HTTPException(status_code=403, detail={"code": "access_denied"}) from None
    except GatewayIdentityUnavailable:
        raise HTTPException(status_code=503, detail={"code": "identity_unavailable"}) from None
    except ValueError:
        raise HTTPException(
            status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    request.scope[PRINCIPAL_SCOPE_KEY] = principal
    return principal


def require_mutation(
    request: Request,
    identity: PanelTokenIdentity,
    public_origin: str,
) -> VerifiedPrincipal:
    principal = request_principal(request, identity)
    if request.headers.get("origin", "") != public_origin:
        raise HTTPException(status_code=403, detail="origin rejected")
    return principal


async def websocket_principal(
    websocket: WebSocket,
    identity: PanelTokenIdentity,
    public_origin: str,
) -> VerifiedPrincipal | None:
    if websocket.headers.get("origin", "") != public_origin:
        await websocket.close(code=4403)
        return None
    try:
        authorization = websocket.headers.get("authorization", "")
        if authorization:
            token = bearer_token(authorization)
        else:
            protocols = websocket.scope.get("subprotocols", [])
            tokens = [value[7:] for value in protocols if value.startswith("bearer.")]
            if WEBSOCKET_PROTOCOL not in protocols or len(tokens) != 1:
                raise ValueError("bearer websocket protocol required")
            token = tokens[0]
        return await identity.verify_async(token)
    except TokenAccessDenied:
        await websocket.close(code=4403)
        return None
    except GatewayIdentityUnavailable:
        await websocket.close(code=1011)
        return None
    except ValueError:
        await websocket.close(code=4401)
        return None


def build_identity_router(identity: PanelTokenIdentity) -> APIRouter:
    router = APIRouter(prefix="/admin/api")

    @router.get("/identity")
    def identity_state(request: Request) -> IdentityState:
        principal = request_principal(request, identity)
        return IdentityState(username=principal.display_name, subject=principal.subject)

    return router
