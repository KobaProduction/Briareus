"""Local managed-browser minimum using the existing BrowserManager.

Each invocation gets a disposable profile and a genuine short Cedar lease.
No browser target has a network route to Core: Internet traffic goes through
the public-address-only egress proxy. The public MCP plane is still separate.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from runtime_peer import PeerIdentity, PeerVerifier, canonical_json
from runtime_peer.server import SignedOwnerApp, serve_unix

from .application.execute_private import ExecutePrivateBrowser, UnknownBrowserOutcome
from .domain.private_effect import BrowserEffectTarget
from .infrastructure.private_admission import PrivateBrowserAdmission
from .infrastructure.private_browser import DisposablePrivateBrowser
from .infrastructure.private_history import FileBrowserHistory
from .presentation.private_call import BrowserCall
from .runtime_views import (
    BrowserCallReceipt,
    RuntimeInspection,
    RuntimeLive,
)


def main() -> None:
    project = UUID(os.environ["WEB_PROJECT_UUID"])
    if project.version != 4 or os.geteuid() != 1005:
        raise ValueError("Real project browser placement required")
    root = Path("/browser")
    if root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077:
        raise ValueError("Owner-private browser storage required")
    revision = int(
        hashlib.sha256(
            canonical_json(
                {"project": str(project), "device": root.stat().st_dev, "inode": root.stat().st_ino}
            )
        ).hexdigest(),
        16,
    )
    resource = "project-web:" + str(project) + ":" + format(revision, "064x")
    effect_target = BrowserEffectTarget(project, resource, revision)
    authority = PeerIdentity.from_file(
        "briareus:authorization", 1002, os.environ["ACCESS_RUNTIME_VERIFY_KEY_FILE"]
    )
    ledger = Path("/var/lib/web-owner")
    if ledger.stat().st_uid != os.geteuid() or ledger.stat().st_mode & 0o077:
        raise ValueError("Private browser operation ledger required")
    admission = PrivateBrowserAdmission(authority, effect_target)
    execute = ExecutePrivateBrowser[BrowserCallReceipt](
        FileBrowserHistory(ledger), DisposablePrivateBrowser(root)
    )
    lock = asyncio.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def live() -> RuntimeLive:
        return RuntimeLive()

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        return JSONResponse(
            {"state": "not_ready", "mcp": "resource_activation_pending"}, status_code=503
        )

    @app.post("/internal/v1/web/inspect", response_model=RuntimeInspection)
    async def inspect(request: Request) -> RuntimeInspection | JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:authorization":
            return JSONResponse({"error": "AUTHORIZATION_OWNER_REQUIRED"}, status_code=403)
        return RuntimeInspection(
            project_uuid=project,
            isolated=True,
            resource_id=resource,
            resource_revision=revision,
            tools=["browser_open"],
        )

    @app.post(
        "/internal/v1/web/call",
        response_model=BrowserCallReceipt,
        response_model_exclude_unset=True,
    )
    async def call(command: BrowserCall) -> BrowserCallReceipt | JSONResponse:
        try:
            async with lock:
                reply = await execute.execute(admission.authorize(command))
                if isinstance(reply, UnknownBrowserOutcome):
                    return JSONResponse({"error": "WEB_OUTCOME_UNKNOWN"}, status_code=503)
                return reply
        except Exception as error:
            logging.getLogger(__name__).warning(
                "browser operation unavailable category=%s", type(error).__name__
            )
            return JSONResponse({"error": "WEB_PERMISSION_OR_OUTCOME_UNAVAILABLE"}, status_code=503)

    verifier = PeerVerifier(
        "briareus:web",
        (
            authority,
            PeerIdentity.from_file(
                "briareus:control-panel-api", 1001, os.environ["WEB_PANEL_VERIFY_KEY_FILE"]
            ),
        ),
    )
    serve_unix(
        SignedOwnerApp(
            app, verifier=verifier, signing_key_file=os.environ["WEB_RUNTIME_SIGNING_KEY_FILE"]
        ),
        os.environ["WEB_RUNTIME_SOCKET"],
        diagnostics_port=8000,
    )


if __name__ == "__main__":
    main()
