"""Forward one signed passive query to its exact private Web supervisor."""

import time

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from node_protocol.browser_observation import OBSERVATION_PATH, BrowserObservationWire
from node_protocol.browser_observation_request import SignedBrowserObservation
from node_protocol.control_auth import CoreVerifier
from node_protocol.json_boundary import decode_json
from node_protocol.naming import worker_name


class BrowserObservationRelay:
    def __init__(self, verifier: CoreVerifier | None, client: httpx.AsyncClient) -> None:
        self._verifier, self._client = verifier, client

    async def forward(self, request: Request) -> JSONResponse:
        try:
            observed = await self._forward(request)
            return JSONResponse(
                observed.model_dump(mode="json"), headers={"cache-control": "no-store"}
            )
        except (ValueError, httpx.HTTPError):
            return JSONResponse(
                {"error": "BROWSER_OBSERVATION_UNAVAILABLE"},
                status_code=503,
                headers={"cache-control": "no-store"},
            )

    async def _forward(self, request: Request) -> BrowserObservationWire:
        if (
            self._verifier is None
            or request.scope.get("raw_path") != OBSERVATION_PATH.encode()
            or request.scope.get("query_string")
            or request.headers.getlist("content-type") != ["application/json"]
            or any(request.headers.getlist(name) for name in ("cookie", "origin", "authorization"))
        ):
            raise ValueError("Private signed browser observation required")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65_536:
                raise ValueError("Bounded observation command required")
        envelope = decode_json(body, SignedBrowserObservation)
        command = self._verifier.verify(
            envelope.command.model_dump_json().encode(), envelope.signature
        )
        target = command.browser_observation
        if target is None:
            raise ValueError("Observation selector required")
        name = worker_name(command.node_uuid, target.placement_uuid, target.fingerprint)
        async with self._client.stream(
            "POST",
            "http://" + name + ".web" + OBSERVATION_PATH,
            content=bytes(body),
            headers={"content-type": "application/json"},
        ) as response:
            if response.status_code != 200:
                raise ValueError("Browser observation unavailable")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 1_048_576:
                    raise ValueError("Bounded browser observation required")
        observed = decode_json(raw, BrowserObservationWire)
        if observed.target != target or command.expires_at <= time.time():
            raise ValueError("Current exact browser observation required")
        return observed
