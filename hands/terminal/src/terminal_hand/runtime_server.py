"""Terminal management controller; shell execution lives in a separate worker."""

from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from runtime_peer import PeerClient, PeerIdentity, PeerVerifier
from runtime_peer.server import SignedOwnerApp, serve_unix

from .worker_server import WorkerCall


def main() -> None:
    signing_key = os.environ["TERMINAL_CONTROLLER_SIGNING_KEY_FILE"]
    worker = PeerClient(name="briareus:terminal", signing_key_file=signing_key,
                        socket_path=os.environ["TERMINAL_WORKER_SOCKET"],
                        owner=PeerIdentity.from_file("briareus:terminal-worker", 0,
                                                     os.environ["TERMINAL_WORKER_VERIFY_KEY_FILE"]))

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await worker.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"state": "live", "mode": "private-owner-runtime"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        # Protected public MCP still needs its own real Rauthy resource and
        # AgentSession admission. A private UI call never pretends to prove it.
        return JSONResponse({"state": "not_ready", "mcp": "resource_activation_pending"}, status_code=503)

    @app.post("/internal/v1/terminal/call")
    async def call(command: WorkerCall) -> JSONResponse:
        try:
            status, body = await worker.call("/internal/v1/terminal/call", command.model_dump(mode="json"))
            return JSONResponse(body, status_code=status)
        except Exception as error:
            logging.getLogger(__name__).warning("terminal worker transport unavailable category=%s", type(error).__name__)
            return JSONResponse({"error": "TERMINAL_OUTCOME_UNKNOWN"}, status_code=503)

    verifier = PeerVerifier("briareus:terminal", (
        PeerIdentity.from_file("briareus:control-panel-api", 1001,
                               os.environ["TERMINAL_PANEL_VERIFY_KEY_FILE"]),
    ))
    serve_unix(SignedOwnerApp(app, verifier=verifier, signing_key_file=signing_key),
                 os.environ["TERMINAL_CONTROLLER_SOCKET"], diagnostics_port=8000)


if __name__ == "__main__":
    main()
