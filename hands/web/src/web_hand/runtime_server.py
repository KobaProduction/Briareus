"""Local managed-browser minimum using the existing BrowserManager.

Each invocation gets a disposable profile and a genuine short Cedar lease.
No browser target has a network route to Core: Internet traffic goes through
the public-address-only egress proxy. The public MCP plane is still separate.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from runtime_peer import PeerIdentity, PeerVerifier, canonical_json
from runtime_peer.server import SignedOwnerApp, serve_unix

from modules.web.browser import BrowserError, BrowserManager
from modules.workspace_compat.legacy_store import WorkspaceFileStore


class BrowserCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permit: str = Field(min_length=80, max_length=8192)
    tool: str
    arguments: dict[str, object] = Field(max_length=1)


def main() -> None:
    project = UUID(os.environ["WEB_PROJECT_UUID"])
    if project.version != 4 or os.geteuid() != 1005:
        raise ValueError("Real project browser placement required")
    root = Path("/browser")
    if root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077:
        raise ValueError("Owner-private browser storage required")
    revision = int(hashlib.sha256(canonical_json({"project": str(project),
        "device": root.stat().st_dev, "inode": root.stat().st_ino})).hexdigest(), 16)
    resource = "project-web:" + str(project) + ":" + format(revision, "064x")
    authority = PeerIdentity.from_file("briareus:authorization", 1002,
                                      os.environ["ACCESS_RUNTIME_VERIFY_KEY_FILE"])
    ledger = Path("/var/lib/web-owner")
    if ledger.stat().st_uid != os.geteuid() or ledger.stat().st_mode & 0o077:
        raise ValueError("Private browser operation ledger required")
    lock = asyncio.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def live():
        return {"state": "live", "mode": "private-owner-runtime"}

    @app.get("/health/ready")
    async def ready():
        return JSONResponse({"state": "not_ready", "mcp": "resource_activation_pending"}, status_code=503)

    @app.post("/internal/v1/web/inspect")
    async def inspect(request: Request):
        if request.scope.get("briareus.service_peer") != "briareus:authorization":
            return JSONResponse({"error": "AUTHORIZATION_OWNER_REQUIRED"}, status_code=403)
        return {"project_uuid": str(project), "isolated": True, "resource_id": resource,
                "resource_revision": revision, "tools": ["browser_open"]}

    @app.post("/internal/v1/web/call")
    async def call(command: BrowserCall):
        try:
            async with lock:
                header = jwt.get_unverified_header(command.permit)
                if header.get("typ") != "briareus-effect-permit+jwt" or header.get("crit"):
                    raise ValueError("Private effect proof required")
                claims = jwt.decode(command.permit, authority.public_key, algorithms=["EdDSA"],
                    issuer="briareus:authorization", audience="briareus:web",
                    options={"require": ["iss", "aud", "iat", "nbf", "exp", "jti", "project_uuid",
                        "actor_uuid", "session_uuid", "grant_revision", "tool", "arguments_digest",
                        "resource_id", "resource_revision", "operation_uuid"]})
                if (type(claims["iat"]) is not int or type(claims["exp"]) is not int
                    or not 0 < claims["exp"] - claims["iat"] <= 20 or claims["nbf"] != claims["iat"]
                    or claims["project_uuid"] != str(project) or claims["resource_id"] != resource
                    or claims["resource_revision"] != revision or command.tool != "browser_open"
                    or claims["tool"] != command.tool or type(claims["grant_revision"]) is not int
                    or claims["grant_revision"] < 1
                    or claims["arguments_digest"] != hashlib.sha256(canonical_json(command.arguments)).hexdigest()):
                    raise ValueError("Browser effect binding mismatch")
                for field in ("jti", "actor_uuid", "session_uuid", "operation_uuid"):
                    value = UUID(claims[field])
                    if value.version != 4 or str(value) != claims[field]:
                        raise ValueError("Canonical effect identity required")
                url = command.arguments.get("url")
                if set(command.arguments) != {"url"} or not isinstance(url, str) or len(url) > 2048:
                    raise ValueError("One bounded browser URL required")
                parsed = urlsplit(url)
                if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or any(ord(ch) < 33 for ch in url)):
                    raise ValueError("Public HTTP(S) URL required")
                operation = str(claims["operation_uuid"])
                fingerprint = hashlib.sha256(canonical_json({"actor": claims["actor_uuid"],
                    "session": claims["session_uuid"], "tool": command.tool, "arguments": command.arguments})).hexdigest()
                target = ledger / (operation + ".json")
                if target.exists():
                    saved = json.loads(target.read_bytes())
                    if saved.get("fingerprint") != fingerprint:
                        raise ValueError("Browser operation identity reused")
                    return saved.get("reply", JSONResponse({"error": "WEB_OUTCOME_UNKNOWN"}, status_code=503))
                if len(list(ledger.glob("*.json"))) >= 10000:
                    raise ValueError("Browser history capacity reached")
                with target.open("x") as pending:
                    os.chmod(target, 0o600)
                    json.dump({"fingerprint": fingerprint}, pending)
                    pending.flush()
                    os.fsync(pending.fileno())
                with tempfile.TemporaryDirectory(prefix="invocation-", dir=root) as work:
                    browser = BrowserManager(workspace=WorkspaceFileStore(Path(work) / "workspace"),
                        profile_dir=Path(work) / "profile", executable_path="/usr/bin/chromium",
                        headless=True, xvfb_enabled=False, timeout_ms=8000, viewport_width=1280,
                        viewport_height=800, max_snapshot_text_chars=16000, max_snapshot_elements=100,
                        chromium_args=("--proxy-server=http://web-egress:8080",
                            "--proxy-bypass-list=<-loopback>", "--disable-quic",
                            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE web-egress"))
                    try:
                        async with asyncio.timeout(min(16, max(0, claims["exp"] - time.time()))):
                            page = await browser.open(url)
                            snapshot = await browser.snapshot(page["page_id"])
                            result = {"page": page, "snapshot": snapshot}
                    finally:
                        await browser._stop_runtime(stop_display=True)
                if time.time() >= claims["exp"]:
                    raise ValueError("Core authority expired before browser output")
                reply = {"operation_uuid": operation, "result": result}
                encoded = canonical_json({"fingerprint": fingerprint, "reply": reply})
                if len(encoded) > 262144:
                    raise ValueError("Browser output budget exceeded")
                temporary = target.with_suffix(".pending")
                with temporary.open("xb") as completed:
                    os.chmod(temporary, 0o600)
                    completed.write(encoded)
                    completed.flush()
                    os.fsync(completed.fileno())
                temporary.replace(target)
                return reply
        except Exception as error:
            logging.getLogger(__name__).warning("browser operation unavailable category=%s", type(error).__name__)
            return JSONResponse({"error": "WEB_PERMISSION_OR_OUTCOME_UNAVAILABLE"}, status_code=503)

    verifier = PeerVerifier("briareus:web", (authority,
        PeerIdentity.from_file("briareus:control-panel-api", 1001, os.environ["WEB_PANEL_VERIFY_KEY_FILE"])))
    serve_unix(SignedOwnerApp(app, verifier=verifier,
        signing_key_file=os.environ["WEB_RUNTIME_SIGNING_KEY_FILE"]),
        os.environ["WEB_RUNTIME_SOCKET"], diagnostics_port=8000)


if __name__ == "__main__":
    main()
