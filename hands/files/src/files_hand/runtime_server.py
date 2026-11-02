"""Authenticated local Files owner: bounded descriptor-confined reads.

This private human-management listener does not enable the public MCP plane.
Its root is provisioned independently and every read needs a fresh real Cedar
decision for the exact actor, session, project, tool and argument digest.
"""

from __future__ import annotations

import hashlib
import os
from uuid import UUID

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from files_hand.application.execute_private import ExecutePrivateFiles, PrivateFilesOutcome
from files_hand.domain.private_effect import PrivateEffectBinding
from files_hand.infrastructure.private_decision import JwtDecisionVerifier
from files_hand.infrastructure.private_execution import SystemWallClock
from files_hand.presentation.private_call import FilesCall
from files_hand.presentation.private_status import FilesInspection, LiveStatus, NotReadyStatus
from modules.project_runtime.workspace_roots import ProjectFileError
from runtime_peer import PeerIdentity, PeerVerifier, canonical_json
from runtime_peer.server import SignedOwnerApp, serve_unix

from ._project_files import TOOLS, ProjectFiles


def main() -> None:
    project = UUID(os.environ["FILES_PROJECT_UUID"])
    if project.version != 4 or os.geteuid() != 1004:
        raise ValueError("A real isolated Files placement is required")
    files = ProjectFiles("/project-data")
    root_info = files.root_info
    revision = int(
        hashlib.sha256(
            canonical_json(
                {
                    "project": str(project),
                    "device": root_info.st_dev,
                    "inode": root_info.st_ino,
                }
            )
        ).hexdigest(),
        16,
    )
    resource = "project-files:" + str(project) + ":" + format(revision, "064x")
    authority = PeerIdentity.from_file(
        "briareus:authorization", 1002, os.environ["ACCESS_RUNTIME_VERIFY_KEY_FILE"]
    )

    execute = ExecutePrivateFiles(JwtDecisionVerifier(authority), files, SystemWallClock(), TOOLS)
    outcome_adapter = TypeAdapter[PrivateFilesOutcome](PrivateFilesOutcome)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def live() -> LiveStatus:
        return LiveStatus()

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        return JSONResponse(
            TypeAdapter(NotReadyStatus).dump_python(NotReadyStatus()), status_code=503
        )

    @app.post("/internal/v1/files/inspect", response_model=None)
    async def inspect(request: Request) -> FilesInspection | JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:authorization":
            return JSONResponse({"error": "AUTHORIZATION_OWNER_REQUIRED"}, status_code=403)
        return FilesInspection(str(project), True, resource, revision, tuple(sorted(TOOLS)))

    @app.post("/internal/v1/files/call")
    async def call(command: FilesCall) -> JSONResponse:
        try:
            arguments = canonical_json(command.call.arguments or {})
            binding = PrivateEffectBinding(
                project,
                resource,
                revision,
                command.call.name,
                hashlib.sha256(arguments).hexdigest(),
            )
            outcome = execute.execute(command.permit, binding, command.query())
            return JSONResponse(outcome_adapter.dump_python(outcome, mode="json"))
        except (jwt.PyJWTError, OSError, ValueError, KeyError, TypeError, ProjectFileError):
            return JSONResponse({"error": "FILES_PERMISSION_OR_PATH_UNAVAILABLE"}, status_code=403)

    verifier = PeerVerifier(
        "briareus:files",
        (
            authority,
            PeerIdentity.from_file(
                "briareus:control-panel-api", 1001, os.environ["FILES_PANEL_VERIFY_KEY_FILE"]
            ),
        ),
    )
    serve_unix(
        SignedOwnerApp(
            app, verifier=verifier, signing_key_file=os.environ["FILES_RUNTIME_SIGNING_KEY_FILE"]
        ),
        os.environ["FILES_RUNTIME_SOCKET"],
        diagnostics_port=8000,
    )


if __name__ == "__main__":
    main()
