"""Read the private last-frame cache without entering the MCP execution boundary."""

import base64

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from node_protocol import Deployment
from node_protocol.browser_observation import (
    OBSERVATION_PATH,
    BrowserObservationSelector,
    BrowserObservationWire,
    BrowserObservedFrameWire,
)
from node_protocol.browser_observation_request import SignedBrowserObservation
from node_protocol.control_auth import CoreVerifier
from node_protocol.json_boundary import decode_json
from web_hand.domain.agent_observation import AgentBrowserObservations, AgentBrowserOwner


def read_observation(
    spec: Deployment,
    selector: BrowserObservationSelector,
    cache: AgentBrowserObservations,
) -> BrowserObservationWire:
    if (
        not spec.enabled
        or spec.release.module != "web"
        or selector.project_uuid != spec.project_uuid
        or selector.placement_uuid != spec.id
        or selector.fingerprint != spec.fingerprint
    ):
        raise ValueError("Current browser placement required")
    frame = cache.read(
        AgentBrowserOwner(
            selector.project_uuid,
            selector.placement_uuid,
            selector.actor_uuid,
            selector.agent_session_uuid,
            selector.grant_revision,
        )
    )
    return BrowserObservationWire(
        target=selector,
        frame=BrowserObservedFrameWire(
            source_request_uuid=frame.request_uuid,
            captured_at=frame.captured_at,
            page_id=frame.page_id,
            url=frame.url,
            title=frame.title,
            png_base64=base64.b64encode(frame.png).decode(),
        )
        if frame
        else None,
    )


class BrowserObservationBoundary:
    def __init__(
        self,
        app: ASGIApp,
        spec: Deployment,
        cache: AgentBrowserObservations,
        verifier: CoreVerifier | None,
    ) -> None:
        self._app, self._spec, self._cache, self._verifier = app, spec, cache, verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != OBSERVATION_PATH:
            await self._app(scope, receive, send)
            return
        request = Request(scope, receive)
        try:
            response = await self._read(request)
        except (ValueError, ValidationError):
            response = JSONResponse({"error": "BROWSER_OBSERVATION_DENIED"}, status_code=403)
        response.headers["cache-control"] = "no-store"
        await response(scope, receive, send)

    async def _read(self, request: Request) -> JSONResponse:
        if (
            self._verifier is None
            or request.method != "POST"
            or request.scope.get("raw_path") != OBSERVATION_PATH.encode()
            or request.scope.get("query_string")
            or request.headers.getlist("content-type") != ["application/json"]
        ):
            raise ValueError("Signed passive browser request required")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65_536:
                raise ValueError("Bounded observation request required")
        envelope = decode_json(body, SignedBrowserObservation)
        command = self._verifier.verify(
            envelope.command.model_dump_json().encode(),
            envelope.signature,
        )
        selector = command.browser_observation
        if selector is None or command.node_uuid != self._spec.node_uuid:
            raise ValueError("Exact browser selector required")
        observed = read_observation(self._spec, selector, self._cache)
        return JSONResponse(observed.model_dump(mode="json"))
