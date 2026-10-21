"""Authenticated local Files owner: bounded descriptor-confined reads.

This private human-management listener does not enable the public MCP plane.
Its root is provisioned independently and every read needs a fresh real Cedar
decision for the exact actor, session, project, tool and argument digest.
"""

from __future__ import annotations

import hashlib
import os
import time
from uuid import UUID

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from runtime_peer import PeerIdentity, PeerVerifier, canonical_json
from runtime_peer.server import SignedOwnerApp, serve_unix

from modules.project_runtime.workspace_roots import ProjectFileError
from ._project_files import ProjectFiles, TOOLS



class FilesCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permit: str = Field(min_length=80, max_length=8192)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, object] = Field(max_length=4)


def main() -> None:
    project = UUID(os.environ["FILES_PROJECT_UUID"])
    if project.version != 4 or os.geteuid() != 1004:
        raise ValueError("A real isolated Files placement is required")
    files = ProjectFiles("/project-data")
    root_info = files.root_info
    revision = int(hashlib.sha256(canonical_json({
        "project": str(project), "device": root_info.st_dev, "inode": root_info.st_ino,
    })).hexdigest(), 16)
    resource = "project-files:" + str(project) + ":" + format(revision, "064x")
    authority = PeerIdentity.from_file("briareus:authorization", 1002,
                                      os.environ["ACCESS_RUNTIME_VERIFY_KEY_FILE"])

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def live():
        return {"state": "live", "mode": "private-owner-runtime"}

    @app.get("/health/ready")
    async def ready():
        return JSONResponse({"state": "not_ready", "mcp": "resource_activation_pending"}, status_code=503)

    @app.post("/internal/v1/files/inspect")
    async def inspect(request: Request):
        if request.scope.get("briareus.service_peer") != "briareus:authorization":
            return JSONResponse({"error": "AUTHORIZATION_OWNER_REQUIRED"}, status_code=403)
        return {"project_uuid": str(project), "isolated": True, "resource_id": resource,
                "resource_revision": revision, "tools": sorted(TOOLS)}

    @app.post("/internal/v1/files/call")
    async def call(command: FilesCall):
        try:
            header = jwt.get_unverified_header(command.permit)
            if header.get("typ") != "briareus-effect-permit+jwt" or header.get("crit"):
                raise ValueError("Private Cedar effect proof required")
            claims = jwt.decode(command.permit, authority.public_key, algorithms=["EdDSA"],
                issuer="briareus:authorization", audience="briareus:files",
                options={"require": ["iss", "aud", "iat", "nbf", "exp", "jti", "project_uuid",
                    "actor_uuid", "session_uuid", "grant_revision", "tool", "arguments_digest",
                    "resource_id", "resource_revision", "operation_uuid"]})
            if (type(claims["iat"]) is not int or type(claims["exp"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= 5 or claims["nbf"] != claims["iat"]
                or claims["project_uuid"] != str(project) or claims["resource_id"] != resource
                or claims["resource_revision"] != revision or command.tool not in TOOLS
                or claims["tool"] != command.tool or type(claims["grant_revision"]) is not int
                or claims["grant_revision"] < 1
                or claims["arguments_digest"] != hashlib.sha256(canonical_json(command.arguments)).hexdigest()):
                raise ValueError("Effect binding mismatch")
            for field in ("jti", "actor_uuid", "session_uuid", "operation_uuid"):
                value = UUID(claims[field])
                if value.version != 4 or str(value) != claims[field]:
                    raise ValueError("Canonical effect identity required")
            result = files.execute(command.tool, command.arguments)
            if time.time() >= claims["exp"]:
                raise ValueError("Core authority expired before output")
            return {"operation_uuid": claims["operation_uuid"], "result": result}
        except (jwt.PyJWTError, OSError, ValueError, KeyError, TypeError, ProjectFileError):
            return JSONResponse({"error": "FILES_PERMISSION_OR_PATH_UNAVAILABLE"}, status_code=403)

    verifier = PeerVerifier("briareus:files", (authority,
        PeerIdentity.from_file("briareus:control-panel-api", 1001, os.environ["FILES_PANEL_VERIFY_KEY_FILE"])))
    serve_unix(SignedOwnerApp(app, verifier=verifier,
        signing_key_file=os.environ["FILES_RUNTIME_SIGNING_KEY_FILE"]),
        os.environ["FILES_RUNTIME_SOCKET"], diagnostics_port=8000)


if __name__ == "__main__":
    main()
