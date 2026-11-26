"""Only Gateway calls the external OIDC authority on behalf of internal services."""

from __future__ import annotations

import hmac

from briareus_oidc import TokenAccessDenied, TokenVerificationError
from briareus_oidc.gateway_contract import (
    INTERNAL_HOST,
    MAX_MESSAGE_BYTES,
    METADATA_PATH,
    VERIFY_PATH,
    GatewayMetadata,
    PrincipalMessage,
    VerifyRequest,
)
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .application.ports import PrincipalVerifier
from .gateway_settings import GatewayAuthSettings


class GatewayIdentityRoutes:
    def __init__(
        self,
        settings: GatewayAuthSettings,
        verifier: PrincipalVerifier,
        service_token: str,
        browser_client_id: str,
    ) -> None:
        if not service_token.strip() or not browser_client_id.strip():
            raise ValueError(
                "Gateway requires private service authentication and public browser client"
            )
        if browser_client_id in {settings.audience, settings.client_id}:
            raise ValueError(
                "Public browser client must be distinct from resource audience and client"
            )
        self._settings = settings
        self._verifier = verifier
        self._service_token = service_token
        self._browser_client_id = browser_client_id
        self.metadata = GatewayMetadata(
            version=1, node_id=settings.node_id, public_origin=settings.public_base_url.rstrip("/")
        )

    def _admission(self, request: Request) -> Response | None:
        if request.headers.getlist("host") != [INTERNAL_HOST]:
            return Response(status_code=404)
        authorization = request.headers.getlist("authorization")
        if len(authorization) != 1 or not hmac.compare_digest(
            authorization[0].encode(), ("Bearer " + self._service_token).encode()
        ):
            return Response(
                status_code=401, headers={"WWW-Authenticate": 'Bearer realm="briareus-internal"'}
            )
        return None

    async def get_metadata(self, request: Request) -> Response:
        denied = self._admission(request)
        if denied is not None:
            return denied
        return JSONResponse(self.metadata.model_dump(), headers={"Cache-Control": "no-store"})

    async def verify(self, request: Request) -> Response:
        denied = self._admission(request)
        if denied is not None:
            return denied
        try:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_MESSAGE_BYTES:
                    return Response(status_code=413)
            token = VerifyRequest.model_validate_json(bytes(body)).token
        except (ValidationError, ValueError):
            return Response(status_code=400)
        try:
            principal = await self._verifier.verify_async(token)
            message = PrincipalMessage.from_verified(self.metadata.node_id, principal)
            response = JSONResponse(message.model_dump(), headers={"Cache-Control": "no-store"})
            if len(response.body) > MAX_MESSAGE_BYTES:
                return Response(status_code=503)
            return response
        except TokenAccessDenied:
            return Response(status_code=403)
        except TokenVerificationError as error:
            if error.reason in {"provider_unavailable", "introspection_failed"}:
                return Response(status_code=503)
            return Response(status_code=401)
        except (ValueError, ValidationError):
            return Response(status_code=503)

    async def browser_config(self, request: Request) -> Response:
        if request.headers.getlist("host") != [self.metadata.public_origin.split("://", 1)[1]]:
            return Response(status_code=421)
        callback = self.metadata.public_origin + "/admin/"
        return JSONResponse(
            {
                "issuer": self._settings.issuer_url,
                "client_id": self._browser_client_id,
                "redirect_uri": callback,
                "post_logout_redirect_uri": callback,
                "scope": " ".join(self._settings.authorization_scopes),
                "audience": self._settings.audience,
            },
            headers={"Cache-Control": "no-store"},
        )

    def routes(self) -> list[Route]:
        return [
            Route(METADATA_PATH, self.get_metadata, methods=["GET"]),
            Route(VERIFY_PATH, self.verify, methods=["POST"]),
            Route("/api/identity/config", self.browser_config, methods=["GET"]),
        ]
